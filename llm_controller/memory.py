import random
from langchain.vectorstores import Chroma
from langchain.embeddings.base import Embeddings
from langchain.docstore.document import Document
import os
from openai import OpenAI
from dotenv import load_dotenv

# 自动加载 .env 文件
load_dotenv()

# Memory 模块独立用硅基流动配置（不影响主决策的 LLM 配置）
# 默认值是硅基流动云端（嵌入模型用量小，免费额度够用）
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
if not SILICONFLOW_API_KEY:
    raise ValueError("memory.py 需要环境变量 SILICONFLOW_API_KEY，请在 .env 中配置 sk-xxx")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_EMBEDDING_MODEL = os.getenv("LLM_EMBEDDING_MODEL", "BAAI/bge-m3")

# 进程级单例嵌入客户端：复用连接，避免每个 DrivingMemory 新建 OpenAI client 泄漏 fd
_embedding_client = None


def _get_embedding_client(api_key, base_url):
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = OpenAI(api_key=api_key, base_url=base_url)
    return _embedding_client



class SiliconFlowEmbeddings(Embeddings):
    """兼容 langchain Embeddings 接口的硅基流动嵌入类，调用 BAAI/bge-m3。"""

    def __init__(self, api_key=None, model=SILICONFLOW_EMBEDDING_MODEL,
                 base_url=SILICONFLOW_BASE_URL):
        self.client = _get_embedding_client(api_key or SILICONFLOW_API_KEY, base_url)
        self.model = model

    def embed_documents(self, texts):
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

    def embed_query(self, text):
        response = self.client.embeddings.create(model=self.model, input=[text])
        return response.data[0].embedding


class DrivingMemory:
    def __init__(self, env) -> None:
        self.embedding = SiliconFlowEmbeddings()
        # 支持外部注入记忆库目录（如 Run_multi_CAV_LLM.py 按 scene/method 隔离），
        # 未注入时保持原行为：./db/<env_id>
        db_base = os.getenv("MEMORY_DB_DIR") or './db/'
        # 注入时用 <MEMORY_DB_DIR>/<env_id>，否则用 ./db/<env_id>（保持原有按场景分库逻辑）
        db_path = os.path.join(db_base, str(env.spec.id))
        os.makedirs(db_base, exist_ok=True)
        self.scenario_memory = Chroma(
            embedding_function=self.embedding,
            persist_directory=db_path
        )

        print("==========Loaded ", db_path, " Memory, Now the database has ", len(self.scenario_memory._collection.get(include=['embeddings'])['embeddings']), " items.==========")


    def retrieveMemory(self, query_scenario, top_k=5):
        """Retrieve the most similar scenarios from memory."""
        similarity_results = self.scenario_memory.similarity_search_with_score(query_scenario, k=top_k)
        fewshot_results = []
        for idx in range(0, len(similarity_results)):
            fewshot_results.append(similarity_results[idx][0].metadata)
        return fewshot_results

    # def retrieveMemory(self, query_scenario, top_k=5):
    #     """Retrieve the most similar scenarios from memory, limited to a certain number of items."""
    #     # Get the first 'limit' embeddings
    #     embeddings_data = self.scenario_memory._collection.get(include=['embeddings', 'documents', 'metadatas'])
    #     limited_embeddings = embeddings_data['embeddings']
    #     limited_documents = embeddings_data['documents']
    #     limited_metadatas = embeddings_data['metadatas']

    #     # Create a temporary Chroma collection with limited items
    #     temp_memory = Chroma(
    #         embedding_function=self.embedding,
    #         persist_directory=None  # Temporary in-memory store
    #     )

    #     # Add the limited data to this temporary collection
    #     temp_memory._collection.add(
    #         embeddings=limited_embeddings,
    #         documents=limited_documents,
    #         metadatas=limited_metadatas
    #     )

    #     # Perform the similarity search on the limited data
    #     similarity_results = temp_memory.similarity_search_with_score(query_scenario, k=top_k)

    #     fewshot_results = []
    #     for idx in range(0, len(similarity_results)):
    #         fewshot_results.append(similarity_results[idx][0].metadata)

    #     return fewshot_results

    def addMemory(self, sce_descrip, human_question, negotiation, action, comments):
        """Add a new scenario to memory."""
        try:
            doc = Document(page_content=sce_descrip, metadata={"human_question": human_question,
                          'negotiation_result': negotiation, 'final_action': action, 'comments': comments})
            self.scenario_memory.add_documents([doc])
            # print(f"Added scenario to memory: {sce_descrip}")
        except Exception as e:
            print(f"Failed to add scenario: {e}")

    def deleteMemory(self, scenario_id):
        """Delete a scenario from memory by its ID."""
        try:
            if scenario_id in self.scenario_memory._collection.ids():
                self.scenario_memory.delete([scenario_id])
                print(f"Deleted scenario with ID: {scenario_id}")
            else:
                print(f"Scenario with ID: {scenario_id} does not exist.")
        except Exception as e:
            print(f"Failed to delete scenario: {e}")

    def combineMemory(self, other_memory):
        """Combine multiple scenarios into a single memory."""
        try:
            other_documents = other_memory.scenario_memory._collection.get(include=['documents', 'metadatas', 'embeddings'])
            current_documents = self.scenario_memory._collection.get(include=['documents', 'metadatas', 'embeddings'])
            for i in range(0, len(other_documents['embeddings'])):
                if other_documents['embeddings'][i] in current_documents['embeddings']:
                    print("Already have one memory item, skip.")
                else:
                    self.scenario_memory._collection.add(
                        embeddings=other_documents['embeddings'][i],
                        metadatas=other_documents['metadatas'][i],
                        documents=other_documents['documents'][i],
                        ids=other_documents['ids'][i]
                    )
            print("Merge complete. Now the database has ", len(
                self.scenario_memory._collection.get(include=['embeddings'])['embeddings']), " items.")
        except Exception as e:
            print(f"Failed to combine scenarios: {e}")

# Example usage:
# if __name__ == "__main__":
#     dm = DrivingMemory()
#     random_speed = random.randint(10, 50)
#     random_distance = random.randint(10, 500)
#     random_delta_ttcp = 125
#     # Add scenarios
#     dm.addMemory('you are driving at intersection you time to collision is 'f'{random_delta_ttcp} second', 'who pass first', 'other first', 'FASTER', 'bad decision')
#     dm.addMemory('you are driving at roundabout you time to collision is 'f'{random_delta_ttcp} second', 'who pass first', 'ego first', 'FASTER', 'good decision')
#
#     # Retrieve similar scenarios
#     results = dm.retrieveMemory("now you are in a intersection, there is conflict infront of you, your time to colision is 135 second", top_k=2)
#     print("Retrieved scenarios:", results)
#
#     # Combine scenarios
#     # dm.combineMemory(dm)


