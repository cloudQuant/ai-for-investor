import sys,os,json,hashlib,re,subprocess,tomllib
from pathlib import Path
from importlib.metadata import version,distribution
r=json.load(open("/tmp/expected.json")); root=Path('/opt/workspace/ai-for-investor'); changes=[]
for row in r['files']:
 p=root/row['path']; h=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
 if h!=row['sha256']:changes.append({'path':row['path'],'actual':h,'expected':row['sha256']})
print(json.dumps({'phase':'source','checked':len(r['files']),'mismatches':changes}),flush=True)
lock=root/'src/backend/requirements-prod.lock'; expected=[]; mismatch=[]
for line in lock.read_text().splitlines():
 m=re.fullmatch(r'([A-Za-z0-9_.-]+)==([^ ;]+).*',line.strip())
 if m:
  name,pin=m.groups();actual=version(name);expected.append(name)
  if actual!=pin:mismatch.append({'name':name,'expected':pin,'actual':actual})
print(json.dumps({'phase':'pins','checked':len(expected),'mismatches':mismatch}),flush=True)
image_project=tomllib.loads((root/'src/backend/pyproject.toml').read_text());current_project=tomllib.loads(r['current_pyproject']);current_project['project']['optional-dependencies']['dev'].remove('python-docx>=1.1.2')
check=subprocess.run([sys.executable,'-m','pip','check'],capture_output=True,text=True)
vcs=json.loads(distribution('backtrader').read_text('direct_url.json'))['vcs_info']
print(json.dumps({'uid':os.getuid(),'python':sys.version.split()[0],'app_files_checked':len(r['files']),'app_source_mismatches':changes,'prod_lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest(),'registry_pins_checked':len(expected),'registry_pin_mismatches':mismatch,'pip_check_exit':check.returncode,'pip_check_stdout':check.stdout.strip(),'pip_check_stderr':check.stderr.strip(),'backtrader_commit':vcs.get('commit_id'),'image_pyproject_sha256':hashlib.sha256((root/'src/backend/pyproject.toml').read_bytes()).hexdigest(),'only_pyproject_delta_is_current_dev_python_docx':image_project==current_project}))
