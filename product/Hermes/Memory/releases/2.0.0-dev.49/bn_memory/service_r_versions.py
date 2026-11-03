"""Explicit compatibility adapter for the CRAN versions tool removed from btw 1.5."""
import hashlib,re
def call(args):
 import requests
 package=args['package_name']
 if not re.fullmatch(r'[A-Za-z][A-Za-z0-9.]{1,80}',package):raise ValueError('cran_package_name_invalid')
 base='https://cloud.r-project.org';desc=base+'/web/packages/'+package+'/DESCRIPTION';archive=base+'/src/contrib/Archive/'+package+'/'
 sources=[];bodies=[]
 with requests.Session() as client:
  client.trust_env=False
  for url in [desc,archive]:
   r=client.get(url,timeout=(10,30),allow_redirects=False)
   sources.append({'url':url,'http_status':r.status_code,'bytes_sha256':hashlib.sha256(r.content).hexdigest(),'original_text':r.text});bodies.append(r.text)
   if r.status_code==429:return {'isError':True,'code':'CRAN_RATE_LIMIT_STOP','sources':sources}
 fields={}
 for line in bodies[0].splitlines():
  if line and not line[0].isspace() and ':' in line:
   key,value=line.split(':',1);fields[key]=value.strip()
 versions=[]
 for line in bodies[1].splitlines():
  m=re.search(r'href="('+re.escape(package)+r'_([^"<>]+)\.tar\.gz)"',line)
  if m:
   stamp=re.search(r'\b\d{4}-\d\d-\d\d\s+\d\d:\d\d\b',line)
   versions.append({'version':m[2],'url':archive+m[1],'archive_last_modified':stamp[0] if stamp else None,'last_modified_is_publication_date':False})
 return {'isError':sources[0]['http_status']!=200,'adapter':'explicit_CRAN_HTTP_compatibility_not_a_btw_native_tool','package':package,'current_version':fields.get('Version'),'current_date_publication':fields.get('Date/Publication'),'archive_versions':versions,'archive_coverage':'returned_official_index' if sources[1]['http_status']==200 else 'archive_index_unavailable','sources':sources,'reading_level':'package_metadata_and_archive_index_not_package_source_review'}
