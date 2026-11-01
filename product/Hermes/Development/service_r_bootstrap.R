invisible(local({
  # utils initialization asks a shell for uname. Use the same observed kernel data
  # without opening a general child-process permission in the R sandbox.
  original <- get("system", envir=baseenv())
  # Sys.which normally starts a shell on this R build. Preserve Unix PATH lookup
  # with filesystem checks; executable discovery does not grant execution.
  direct_which <- function(names) {
    paths <- strsplit(Sys.getenv("PATH"), .Platform$path.sep, fixed=TRUE)[[1L]]
    result <- vapply(names, function(name) {
      candidates <- if (grepl("/",name,fixed=TRUE)) name else file.path(paths,name)
      candidates <- candidates[file.exists(candidates) & file.access(candidates,1L)==0L]
      if (length(candidates)) candidates[[1L]] else ""
    }, character(1L), USE.NAMES=TRUE)
    result
  }
  unlockBinding("Sys.which", baseenv()); assign("Sys.which", direct_which, envir=baseenv()); lockBinding("Sys.which", baseenv())
  fixed <- function(command, intern=FALSE, ...) {
    info <- Sys.info()
    value <- switch(command,
      "uname -sr 2>/dev/null||echo darwin"=paste(info[["sysname"]], info[["release"]]),
      "uname -a"=paste(info[c("sysname","nodename","release","version","machine")], collapse=" "),
      stop("R initialization requested an unreviewed external command"))
    if (!intern) stop("Only observed uname output is supported during initialization")
    value
  }
  unlockBinding("system", baseenv()); assign("system", fixed, envir=baseenv()); lockBinding("system", baseenv())
  on.exit({unlockBinding("system", baseenv()); assign("system", original, envir=baseenv()); lockBinding("system", baseenv())}, add=TRUE)
  library("utils"); library("stats"); library("grDevices"); library("graphics")
}))
if (nzchar(Sys.getenv("HERMES_R_PROBE"))) {
  cat(R.version.string,"\n")
  cat(as.character(utils::packageVersion("mcptools")),"\n")
  cat(as.character(utils::packageVersion("btw")),"\n")
} else {
  source(file.path(Sys.getenv("HERMES_R_CODE_ROOT"), "server.R"), local=.GlobalEnv)
}
