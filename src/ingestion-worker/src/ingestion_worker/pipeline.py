class Pipeline:

    def __init__(self, org_id, kb_id):
        self.org_id = org_id
        self.kb_id = kb_id

    async def run(self):
        raw_data = self._read()
        transformed_data = self._transform()
        self._load(transformed_data)

    async def _read(self):
        pass

    async def _transform(self):
        pass

    async def _load(self, data):
        pass
