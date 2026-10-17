import httpx
from config import settings
from services.utils import Signer



class RagService:
    def __init__(self, config=settings):
        # 1. 加载基础鉴权配置
        self.ak = config.VOLC_AK
        self.sk = config.VOLC_SK
        
        # 2. 知识库特有配置
        self.collection_name = config.KB_COLLECTION_NAME  # 知识库集合名称
        self.project_name = config.KB_PROJECT_NAME      # 项目名称
        self.account_id = config.VOLC_ACCOUNT_ID        # 火山引擎主账号ID (必填)

        
        # 知识库服务的固定配置
        self.host = "api-knowledgebase.mlp.cn-beijing.volces.com"
        self.region = "cn-north-1" # 示例代码中使用的是 cn-north-1
        self.service = "air"       # 知识库服务的 Service 名通常为 air

    async def retrieve(self, query: str) -> str:
        """
        根据用户问题检索知识库
        :param query: 用户查询语句
        :return: 整合后的上下文文本
        """
        # 基础校验
        if not all(
            (
                self.ak,
                self.sk,
                self.collection_name,
                self.project_name,
                self.account_id,
            )
        ):
            print("⚠️ [RagService] 配置缺失")
            return ""

        path = "/api/knowledge/collection/search_knowledge"
        
        # 3. 构造请求体 (参考官方示例)
        body = {
            "project": self.project_name,
            "name": self.collection_name,
            "query": query,
            "limit": 1, # 获取相关度最高的前3条
            "pre_processing": {
                "need_instruction": True,
                "return_token_usage": True,
                "messages": [{"role": "user", "content": query}]
            },
            "post_processing": {
                "get_attachment_link": True
            }
        }

        # 4. 构造 Header
        # 注意：V-Account-Id 是知识库接口必须的
        headers = {
            "Host": self.host,
            "Content-Type": "application/json",
            "V-Account-Id": self.account_id 
        }

        # 构造待签名的请求数据
        request_data = {
            "method": "POST",
            "path": path,
            "headers": headers,
            "body": body,
            "params": {}
        }



        try:
            # 5. 计算签名 (复用 utils.py 中的 Signer)
            # 知识库使用的是 air / cn-north-1
            signer = Signer(request_data, service=self.service, region=self.region)
            signer.add_authorization({
                "accessKeyId": self.ak,
                "secretKey": self.sk
            })
            
            # 6. 发送异步请求
            url = f"https://{self.host}{path}"
            
            async with httpx.AsyncClient() as client:
                # request_data['headers'] 已经被 signer 修改，包含了 Authorization 字段
                resp = await client.post(
                    url, 
                    headers=request_data["headers"], 
                    json=body,
                    timeout=10.0
                )

            # 6. 解析响应内容
            if resp.status_code != 200:
                print(f"❌ [RagService] 请求失败: {resp.status_code}")
                return ""

            data = resp.json()
            
            # --- 核心提取逻辑 ---
            # 1. 按照层级定位到 result_list
            # 使用 .get() 级联获取，防止中间某个 Key 缺失导致报错
            result_list = data.get("data", {}).get("result_list", [])
            
            # 2. 提取所有 item 中的 content
            # 兼容多条数据：遍历列表，只取 content 字段不为空的部分
            contents = [item.get("content", "") for item in result_list if item.get("content")]
            
            
            if not contents:
                print(f"⚠️ [RagService] 未检索到匹配的知识内容")
                return ""

            # 3. 将多条 content 拼接成一个完整的字符串返回
            # 使用双换行符分隔不同的知识块，方便 LLM 区分
            context_text = "\n\n".join(contents)
            
            print(f"✅ [RagService] 成功提取 {len(contents)} 条知识内容")
            return context_text


        except Exception:
            print("❌ [RagService] 请求异常")
            return ""

# 实例化单例
rag_service = RagService()
