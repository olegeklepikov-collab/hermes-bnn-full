"""Official R.framework binaries in a new BNN-only library, no shared-library edits."""
from pathlib import Path
import hashlib,json,os,subprocess
from service_docs import ROOT,BASE,dump
def install():
 target=ROOT/'Services/software/R/framework-library';target.mkdir(exist_ok=True)
 script=ROOT/'Services/software/R/install-framework.R'
 script.write_text('lib <- '+json.dumps(str(target))+'\n.libPaths(c(lib,.Library))\noptions(repos=c(CRAN="https://cloud.r-project.org"),timeout=90)\nrequired<-c("mcptools","btw","ggplot2")\nmissing<-required[!vapply(required,function(p)dir.exists(file.path(lib,p)),logical(1))]\nif(length(missing)) install.packages(missing,lib=lib,type="binary",dependencies=NA)\nstopifnot(all(vapply(required,requireNamespace,logical(1),quietly=TRUE)))\ndb<-installed.packages(); deps<-tools::package_dependencies(required,db=db,which=c("Depends","Imports","LinkingTo"),recursive=TRUE)\nclosure<-sort(unique(c(required,unlist(deps)))); closure<-closure[!is.na(closure)&closure!="R"]\nfor(p in closure) {\n if(!identical(db[p,"Priority"],"base") && !dir.exists(file.path(lib,p))) {\n  src<-file.path(db[p,"LibPath"],p); stopifnot(startsWith(normalizePath(src),normalizePath(.Library)))\n  stopifnot(file.copy(src,lib,recursive=TRUE,copy.mode=TRUE,copy.date=TRUE))\n }\n}\njsonlite::write_json(list(packages=as.list(closure),locations=as.list(setNames(vapply(closure,find.package,character(1)),closure))),file.path(dirname(lib),"package-closure.json"),auto_unbox=TRUE,pretty=TRUE)\nprint(vapply(required,function(p) as.character(packageVersion(p)),character(1)))\n')
 env={k:v for k,v in os.environ.items() if k in {'HOME','PATH','TMPDIR','LANG','LC_ALL'}}
 env.update(R_LIBS_USER=str(target),R_LIBS_SITE='/nonexistent',R_PROFILE_USER='/dev/null',R_ENVIRON_USER='/dev/null',R_MAKEVARS_USER='/dev/null',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
 with (BASE/'r-framework-install.log').open('a') as log:
  p=subprocess.run(['/Library/Frameworks/R.framework/Resources/bin/Rscript','--vanilla',str(script)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
 result={'ok':p.returncode==0,'exit_code':p.returncode,'target':str(target),'packages':sorted(p.name for p in target.iterdir() if p.is_dir()),'official_binary_repository':'https://cloud.r-project.org','shared_conda_library_changed':False,'system_framework_changed':False}
 dump(BASE/'r-framework-install-status.json',result);return result
