import uuid
from datetime import datetime,date
from sqlalchemy import String,Text,Date,DateTime,Boolean,BigInteger,ForeignKey,UniqueConstraint,Integer
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column
def uid(): return str(uuid.uuid4())
class Base(DeclarativeBase): pass
class Person(Base):
 __tablename__="people"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); name:Mapped[str]=mapped_column(String(250),index=True); relation:Mapped[str|None]=mapped_column(String(100)); notes:Mapped[str|None]=mapped_column(Text); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Case(Base):
 __tablename__="cases"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); title:Mapped[str]=mapped_column(String(300),index=True); status:Mapped[str]=mapped_column(String(50),default="active"); notes:Mapped[str|None]=mapped_column(Text); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Document(Base):
 __tablename__="documents"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); title:Mapped[str]=mapped_column(String(400),index=True); category:Mapped[str]=mapped_column(String(100),index=True); subtype:Mapped[str|None]=mapped_column(String(100)); person_id:Mapped[str|None]=mapped_column(ForeignKey("people.id"),index=True); case_id:Mapped[str|None]=mapped_column(ForeignKey("cases.id"),index=True); country:Mapped[str|None]=mapped_column(String(100)); issuer:Mapped[str|None]=mapped_column(String(250)); document_number:Mapped[str|None]=mapped_column(String(150),index=True); issue_date:Mapped[date|None]=mapped_column(Date); expiry_date:Mapped[date|None]=mapped_column(Date,index=True); notes:Mapped[str|None]=mapped_column(Text); favorite:Mapped[bool]=mapped_column(Boolean,default=False); deleted:Mapped[bool]=mapped_column(Boolean,default=False,index=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True); updated_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
class DocumentVersion(Base):
 __tablename__="document_versions"; __table_args__=(UniqueConstraint("document_id","version"),); id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); document_id:Mapped[str]=mapped_column(ForeignKey("documents.id"),index=True); version:Mapped[int]=mapped_column(Integer); kind:Mapped[str]=mapped_column(String(50),default="original"); original_name:Mapped[str]=mapped_column(String(500)); stored_name:Mapped[str]=mapped_column(String(500),unique=True); mime_type:Mapped[str|None]=mapped_column(String(200)); size:Mapped[int]=mapped_column(BigInteger); sha256:Mapped[str]=mapped_column(String(64),index=True); ocr_status:Mapped[str]=mapped_column(String(30),default="pending"); ocr_text:Mapped[str|None]=mapped_column(Text); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Tag(Base):
 __tablename__="tags"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); name:Mapped[str]=mapped_column(String(100),unique=True,index=True)
class DocumentTag(Base):
 __tablename__="document_tags"; document_id:Mapped[str]=mapped_column(ForeignKey("documents.id"),primary_key=True); tag_id:Mapped[str]=mapped_column(ForeignKey("tags.id"),primary_key=True)
class Relation(Base):
 __tablename__="document_relations"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); source_id:Mapped[str]=mapped_column(ForeignKey("documents.id"),index=True); target_id:Mapped[str]=mapped_column(ForeignKey("documents.id"),index=True); relation:Mapped[str]=mapped_column(String(50))
class Audit(Base):
 __tablename__="audit_logs"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); action:Mapped[str]=mapped_column(String(100),index=True); object_type:Mapped[str]=mapped_column(String(50)); object_id:Mapped[str|None]=mapped_column(String(36),index=True); detail:Mapped[str|None]=mapped_column(Text); at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)
class Reminder(Base):
 __tablename__="reminders"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); document_id:Mapped[str]=mapped_column(ForeignKey("documents.id"),index=True); remind_on:Mapped[date]=mapped_column(Date,index=True); note:Mapped[str|None]=mapped_column(Text); done:Mapped[bool]=mapped_column(Boolean,default=False); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)

class User(Base):
 __tablename__="users"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); username:Mapped[str]=mapped_column(String(100),unique=True,index=True); password_hash:Mapped[str]=mapped_column(String(500)); is_admin:Mapped[bool]=mapped_column(Boolean,default=True); active:Mapped[bool]=mapped_column(Boolean,default=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow); last_login:Mapped[datetime|None]=mapped_column(DateTime)
class SessionToken(Base):
 __tablename__="sessions"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); user_id:Mapped[str]=mapped_column(ForeignKey("users.id"),index=True); token_hash:Mapped[str]=mapped_column(String(64),unique=True,index=True); csrf_hash:Mapped[str]=mapped_column(String(64)); expires_at:Mapped[datetime]=mapped_column(DateTime,index=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)

class ShareLink(Base):
 __tablename__="share_links"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); document_id:Mapped[str]=mapped_column(ForeignKey("documents.id"),index=True); token_hash:Mapped[str]=mapped_column(String(64),unique=True,index=True); expires_at:Mapped[datetime]=mapped_column(DateTime,index=True); max_downloads:Mapped[int]=mapped_column(Integer,default=1); downloads:Mapped[int]=mapped_column(Integer,default=0); active:Mapped[bool]=mapped_column(Boolean,default=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)

class Notification(Base):
 __tablename__="notifications"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); kind:Mapped[str]=mapped_column(String(50),index=True); title:Mapped[str]=mapped_column(String(300)); body:Mapped[str|None]=mapped_column(Text); document_id:Mapped[str|None]=mapped_column(ForeignKey("documents.id"),index=True); read:Mapped[bool]=mapped_column(Boolean,default=False,index=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)

class ManagedAsset(Base):
 __tablename__="managed_assets"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); name:Mapped[str]=mapped_column(String(200),index=True); kind:Mapped[str]=mapped_column(String(50),index=True); address:Mapped[str]=mapped_column(String(300)); port:Mapped[int|None]=mapped_column(Integer); protocol:Mapped[str]=mapped_column(String(30),default="tcp"); enabled:Mapped[bool]=mapped_column(Boolean,default=True); notes:Mapped[str|None]=mapped_column(Text); last_status:Mapped[str]=mapped_column(String(30),default="unknown",index=True); last_latency_ms:Mapped[int|None]=mapped_column(Integer); last_seen:Mapped[datetime|None]=mapped_column(DateTime); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class AssetCheck(Base):
 __tablename__="asset_checks"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); asset_id:Mapped[str]=mapped_column(ForeignKey("managed_assets.id"),index=True); check_type:Mapped[str]=mapped_column(String(30),default="tcp"); path:Mapped[str|None]=mapped_column(String(300)); enabled:Mapped[bool]=mapped_column(Boolean,default=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class CheckResult(Base):
 __tablename__="check_results"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); asset_id:Mapped[str]=mapped_column(ForeignKey("managed_assets.id"),index=True); status:Mapped[str]=mapped_column(String(30),index=True); latency_ms:Mapped[int|None]=mapped_column(Integer); message:Mapped[str|None]=mapped_column(Text); checked_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)
class SystemAlert(Base):
 __tablename__="system_alerts"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); asset_id:Mapped[str|None]=mapped_column(ForeignKey("managed_assets.id"),index=True); severity:Mapped[str]=mapped_column(String(30),index=True); title:Mapped[str]=mapped_column(String(300)); body:Mapped[str|None]=mapped_column(Text); acknowledged:Mapped[bool]=mapped_column(Boolean,default=False,index=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)

class ConnectorSample(Base):
 __tablename__="connector_samples"; id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); connector:Mapped[str]=mapped_column(String(80),index=True); status:Mapped[str]=mapped_column(String(30),index=True); summary_json:Mapped[str|None]=mapped_column(Text); sampled_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)

class NetworkChangeJob(Base):
 __tablename__="network_change_jobs"
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 device_id:Mapped[str]=mapped_column(String(120),index=True)
 device_name:Mapped[str]=mapped_column(String(200),index=True)
 requested_by:Mapped[str]=mapped_column(String(100),index=True)
 status:Mapped[str]=mapped_column(String(30),default="queued",index=True)
 change_commands:Mapped[str]=mapped_column(Text)
 precheck_commands:Mapped[str|None]=mapped_column(Text)
 postcheck_commands:Mapped[str|None]=mapped_column(Text)
 rollback_commands:Mapped[str|None]=mapped_column(Text)
 backup_text:Mapped[str|None]=mapped_column(Text)
 precheck_output:Mapped[str|None]=mapped_column(Text)
 change_output:Mapped[str|None]=mapped_column(Text)
 postcheck_output:Mapped[str|None]=mapped_column(Text)
 error:Mapped[str|None]=mapped_column(Text)
 created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)
 started_at:Mapped[datetime|None]=mapped_column(DateTime)
 finished_at:Mapped[datetime|None]=mapped_column(DateTime)

class DeviceConfigSnapshot(Base):
 __tablename__="device_config_snapshots"
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 device_id:Mapped[str]=mapped_column(String(120),index=True)
 device_name:Mapped[str]=mapped_column(String(200),index=True)
 config_text:Mapped[str]=mapped_column(Text)
 sha256:Mapped[str]=mapped_column(String(64),index=True)
 source:Mapped[str]=mapped_column(String(50),default="manual")
 created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)
