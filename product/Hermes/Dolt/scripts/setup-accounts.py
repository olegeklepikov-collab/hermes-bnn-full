from pathlib import Path
import json,secrets,pymysql,os,socket,time
z=Path(__file__).resolve().parents[1];fp=z/'config/credentials.json'
if fp.exists():creds=json.loads(fp.read_text())
else:
 creds={'root_password':secrets.token_urlsafe(36),'agent_password':secrets.token_urlsafe(36),'initialized':False};fp.write_text(json.dumps(creds));fp.chmod(0o600)
for attempt in range(40):
 try:
  with socket.create_connection(('127.0.0.1',33697),timeout=.5):break
 except OSError:time.sleep(.25)
try:conn=pymysql.connect(host='127.0.0.1',port=33697,user='root',password=creds['root_password'],autocommit=True)
except pymysql.OperationalError:
 if creds['initialized']:raise
 conn=pymysql.connect(host='127.0.0.1',port=33697,user='root',password='',autocommit=True)
with conn:
 with conn.cursor() as cur:
  cur.execute('SELECT User,Host FROM mysql.user WHERE User=%s',('root',));roots=cur.fetchall()
  for user,host in roots:cur.execute('ALTER USER %s@%s IDENTIFIED BY %s',(user,host,creds['root_password']))
  cur.execute('CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s',('hermes_bn','localhost',creds['agent_password']))
  cur.execute('ALTER USER %s@%s IDENTIFIED BY %s',('hermes_bn','localhost',creds['agent_password']))
  cur.execute('GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,DROP,INDEX,EXECUTE ON knowledgework.* TO %s@%s',('hermes_bn','localhost'))
  cur.execute("USE knowledgework")
  cur.execute("CREATE TABLE IF NOT EXISTS research_sources (dataset_id VARCHAR(80) PRIMARY KEY, source_file TEXT NOT NULL, source_sha256 CHAR(64) NOT NULL, imported_at DATETIME(6) NOT NULL, row_count BIGINT NOT NULL, source_format VARCHAR(20) NOT NULL, note TEXT)")
  cur.execute("CREATE TABLE IF NOT EXISTS research_records (dataset_id VARCHAR(80) NOT NULL, record_id BIGINT NOT NULL, payload JSON NOT NULL, PRIMARY KEY(dataset_id,record_id), FOREIGN KEY (dataset_id) REFERENCES research_sources(dataset_id))")
  cur.execute("CALL DOLT_ADD('.')")
  cur.execute("CALL DOLT_COMMIT('-m','Initialize Hermes BN research tables','--allow-empty')")
creds['initialized']=True;fp.write_text(json.dumps(creds));fp.chmod(0o600)
with pymysql.connect(host='127.0.0.1',port=33697,user='hermes_bn',password=creds['agent_password'],database='knowledgework',autocommit=True) as conn:
 with conn.cursor() as cur:cur.execute('SELECT DOLT_VERSION(),DATABASE()');version,db=cur.fetchone();assert db=='knowledgework'
(z/'checks/sql-account-setup.json').write_text(json.dumps({'version':version,'database':db,'user':'hermes_bn','root_password_set':True,'credential_file_permissions':'0600','sql_bind':'127.0.0.1:33697','schema_initialized':True},indent=2));print('Local SQL account and research tables verified; credentials kept private')
