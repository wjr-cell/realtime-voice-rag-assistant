import threading

from volcenginesdkarkruntime import Ark 
from config import settings

class LLMService:
    def __init__(self, config=settings):
        self.config = config
        self.client = None
        self._client_lock = threading.Lock()

    def _get_client(self):
        if self.client is None:
            with self._client_lock:
                if self.client is None:
                    self.client = Ark(
                        base_url="https://ark.cn-beijing.volces.com/api/v3",
                        api_key=self.config.ARK_API_KEY,
                        timeout=1800,
                    )
        return self.client

    def chat_stream(self, history_messages: list, rag_context: str = ""):
        """
        流式对话
        :param history_messages: 对话历史
        :param rag_context: 从 rag_service 检索出来的背景知识
        """
        # --- 1. 定义极其严格的系统提示词 ---
        # 使用三引号，保持代码与输出格式一致
        system_content = """
        # 角色
        你是【小智】，AI助手。

        # 核心任务
        1. 依据【参考知识库】回答咨询。
        2. 知识库有内容：直接复用库里那些“带劲”的话，不要美化成废话。
        3. 知识库没内容：执行【拦截话术】。

        # 行为准则
        - **不废话**：用短句，多用祈使句。不要说“理解您的意思”，直接给答案。
        - **反幻觉**：严禁编造。库里没有，就说：“抱歉，这块信息库还没更新”
        


                """.strip()

        # --- 2. 构造最终发送给模型的消息序列 ---
        # messages = [{"role": "system", "content": system_content}]

        system_blocks = [system_content]

        if rag_context:
            # 使用明确的定界符，帮助模型在毫秒内定位知识
            system_blocks.append(f"### 参考知识库（绝对准则）\n{rag_context.strip()}")

        # 合并为一条
        final_system_prompt = "\n\n".join(system_blocks)

        # 最终的消息序列
        messages = [{"role": "system", "content": final_system_prompt}]

        # 加入历史对话（确保包含用户最新的问题）
        messages.extend(history_messages)

        try:
            client = self._get_client()
            print(f"🚀 发起流式调用 (Endpoint: {self.config.ARK_ENDPOINT_ID})")
            
            stream = client.chat.completions.create(
                model=self.config.ARK_ENDPOINT_ID,
                messages=messages,
                temperature=0.3, # 降低随机性，确保回答更严谨地贴合 RAG
                stream=True,
                stream_options={"include_usage": True},
            )

            for chunk in stream:
                yield chunk

        except Exception:
            print("❌ LLM 调用失败")
            yield None

llm_service = LLMService()
