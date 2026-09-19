const FOLDER_ID = "1aDh5o-paAS7HwFRnKBo2EUHYXe-LV8PP";
const ENDPOINT = "https://hossein-hub.tailf8fccb.ts.net/api/google-drive-push/upload";
const TOKEN = "__DRIVE_PUSH_TOKEN__";

function syncHosseinHub() {
  const props = PropertiesService.getScriptProperties();
  const lastRun = Number(props.getProperty("lastRunMs") || "0");
  const now = Date.now();
  const folder = DriveApp.getFolderById(FOLDER_ID);
  const files = folder.getFiles();
  const allowed = new Set(["application/pdf","image/jpeg","image/png","image/webp","image/tiff"]);
  const errors = [];

  while (files.hasNext()) {
    const file = files.next();
    if (!allowed.has(file.getMimeType())) continue;
    if (file.getLastUpdated().getTime() <= lastRun) continue;

    try {
      const response = UrlFetchApp.fetch(ENDPOINT, {
        method: "post",
        headers: {
          "X-Drive-Token": TOKEN,
          "X-Drive-File-Id": file.getId()
        },
        payload: { file: file.getBlob().setName(file.getName()) },
        muteHttpExceptions: true
      });
      const code = response.getResponseCode();
      if (code < 200 || code >= 300) {
        throw new Error("HTTP " + code + ": " + response.getContentText());
      }
    } catch (e) {
      errors.push(file.getName() + ": " + e.message);
    }
  }

  if (errors.length) throw new Error(errors.join("\n"));
  props.setProperty("lastRunMs", String(now));
  syncHosseinHubRenames();
}

function installHosseinHubTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger("syncHosseinHub").timeBased().everyMinutes(5).create();
  syncHosseinHub();
}


function syncHosseinHubRenames() {
  const response = UrlFetchApp.fetch(ENDPOINT.replace("/upload","/rename-jobs"), {
    method: "get",
    headers: {"X-Drive-Token": TOKEN},
    muteHttpExceptions: true
  });
  if (response.getResponseCode() !== 200) return;
  const jobs = JSON.parse(response.getContentText()).jobs || [];
  jobs.forEach(j => {
    try {
      const f=DriveApp.getFileById(j.fileId);
      if (f.getName() !== j.name) f.setName(j.name);
    } catch(e) {}
  });
}

function applyHosseinHubRenames() { syncHosseinHubRenames(); }
