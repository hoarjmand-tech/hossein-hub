from pydantic import BaseModel
class PersonCreate(BaseModel): name:str; relation:str|None=None; notes:str|None=None
class CaseCreate(BaseModel): title:str; status:str="active"; notes:str|None=None
class RelationCreate(BaseModel): target_id:str; relation:str
class DocumentPatch(BaseModel):
    title:str|None=None; category:str|None=None; subtype:str|None=None; country:str|None=None; issuer:str|None=None; document_number:str|None=None; notes:str|None=None; favorite:bool|None=None
