from pathlib import Path
from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase

kb_path = Path("dummy_data/f1_kb.json")
f1_kb = KnowledgeBase.from_json_file(kb_path)

schema_registy = f1_kb.get_graph_schem_registry_records()

print(schema_registy)
