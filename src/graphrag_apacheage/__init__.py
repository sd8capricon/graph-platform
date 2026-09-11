from graphrag_apacheage.config import load_config


def main() -> None:
    settings = load_config()
    print(settings.embedding_dimension)
    print("Hello from graphrag-apacheage!")
