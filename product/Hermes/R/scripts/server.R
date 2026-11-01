local({
  root <- Sys.getenv("HERMES_BN_R_HOME")
  stopifnot(nzchar(root), dir.exists(root))
  dir.create(file.path(root, "projects", "default"), recursive=TRUE, showWarnings=FALSE)
  setwd(file.path(root, "projects", "default"))
  options(repos=c(CRAN="https://cloud.r-project.org"), timeout=30,
          btw.run_r.enabled=TRUE,
          btw.run_r.plot_size=768L,
          btw.run_r.plot_aspect_ratio="3:2")
  # mcptools 1.0.3 does not implement ping and advertises unsupported resources/prompts.
  namespace <- asNamespace("mcptools")
  old_handler <- get("handle_message_from_client", envir=namespace)
  ping_handler <- function(line) {
    message <- tryCatch(jsonlite::parse_json(line), error=function(e) NULL)
    if (is.list(message) && identical(message$method, "ping") && !is.null(message$id)) {
      response <- get("jsonrpc_response", envir=namespace)(
        message$id, get("named_list", envir=namespace)())
      get("cat_json", envir=namespace)(response)
    } else {
      old_handler(line)
    }
  }
  old_capabilities <- get("capabilities", envir=namespace)
  actual_capabilities <- function(protocol_version) {
    result <- old_capabilities(protocol_version)
    result$capabilities$resources <- NULL
    result$capabilities$prompts <- NULL
    result$serverInfo <- list(name="Hermes BN R",
      version=paste0(utils::packageVersion("mcptools"), "-hermesbn.1"))
    result
  }
  assignInNamespace("handle_message_from_client", ping_handler, "mcptools")
  assignInNamespace("capabilities", actual_capabilities, "mcptools")
  # Use the same CRAN endpoints with an explicit network timeout and the Published field.
  btw_namespace <- asNamespace("btw")
  cran_current <- function(package_name) {
    request <- httr2::req_timeout(httr2::request("https://cran.r-project.org/src/contrib/PACKAGES.rds"), 30)
    bytes <- httr2::resp_body_raw(httr2::req_perform(request))
    metadata_file <- tempfile(fileext=".rds")
    on.exit(unlink(metadata_file), add=TRUE)
    writeBin(bytes, metadata_file)
    packages <- readRDS(metadata_file)
    if (!package_name %in% rownames(packages)) {
      return(get("cran_versions_data", envir=btw_namespace)())
    }
    stamp <- get("format_cran_timestamp", envir=btw_namespace)(packages[package_name, "Published"])
    get("cran_versions_data", envir=btw_namespace)(
      version=packages[package_name, "Version"], released=as.Date(stamp),
      released_at=stamp, current=TRUE,
      tarball_url=sprintf("https://cran.r-project.org/src/contrib/%s_%s.tar.gz",
        package_name, packages[package_name,"Version"]))
  }
  cran_archive <- function(package_name) {
    url <- sprintf("https://cran.r-project.org/src/contrib/Archive/%s/",
      utils::URLencode(package_name, reserved=TRUE))
    request <- httr2::req_timeout(httr2::request(url), 30)
    xml2::read_html(httr2::resp_body_raw(httr2::req_perform(request)))
  }
  assignInNamespace("cran_current_version", cran_current, "btw")
  assignInNamespace("cran_archive_page", cran_archive, "btw")
  tools <- btw::btw_tools("docs", "env", "sessioninfo", "cran", "run")
  run_index <- which(vapply(tools, function(tool) tool@name == "btw_tool_run_r", logical(1)))
  stopifnot(length(run_index) == 1L)
  run <- tools[[run_index]]
  original <- S7::S7_data(run)
  S7::S7_data(run) <- function(code, `_intent`="") {
    setTimeLimit(cpu=Inf, elapsed=240, transient=TRUE)
    on.exit(setTimeLimit(cpu=Inf, elapsed=Inf, transient=FALSE), add=TRUE)
    result <- original(code=code, `_intent`=`_intent`)
    if (identical(result@extra$status, "error")) {
      result@error <- "R code failed; captured output and error details are retained."
    }
    result
  }
  run@description <- paste(run@description,
    "Hermes BN: local R on AgentRuntime2. This process retains R objects between calls; other client processes have separate sessions. Each evaluation has a best-effort 240-second R time limit. Captured R errors set MCP isError=true. The work directory is R/projects/default; files for another project must use explicit paths.",
    sep="\n\n")
  tools[[run_index]] <- run
  mcptools::mcp_server(tools=tools, session_tools=FALSE)
})
