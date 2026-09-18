from datetime import date
from pydantic import BaseModel,Field
class PersonCreate(BaseModel): name:str=Field(min_length=1,max_length=250); relation:str|None=None; notes:str|None=None
class CaseCreate(BaseModel): title:str=Field(min_length=1,max_length=300); status:str="active"; notes:str|None=None
class RelationCreate(BaseModel): target_id:str; relation:str
class DocumentPatch(BaseModel):
 title:str|None=None; category:str|None=None; subtype:str|None=None; person_id:str|None=None; case_id:str|None=None; country:str|None=None; issuer:str|None=None; document_number:str|None=None; issue_date:date|None=None; expiry_date:date|None=None; notes:str|None=None; favorite:bool|None=None
