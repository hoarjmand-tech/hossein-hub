const FOLDER_ID = "1aDh5o-paAS7HwFRnKBo2EUHYXe-LV8PP";
const ENDPOINT = "https://hossein-hub.tailf8fccb.ts.net/api/google-drive-push/upload";
const TOKEN = "e7T3VElFJMIFCyT9xiXo2cFSVaYXbQlf2qYENd-ZkJFAzKxt5tdNrFk6Y3oHq7xF";

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  const body = JSON.parse((e && e.postData && e.postData.contents) || "{}");
  if (body.action === "list") return json_(listDrive_(body.folderId || FOLDER_ID));
  if (body.action === "import") return json_(importDriveFile_(body.fileId));
  return json_({ok:false,error:"عملیات ناشناخته است"});
}

function listDrive_(folderId) {
  const folder = DriveApp.getFolderById(folderId), items = [];
  const folders = folder.getFolders();
  while (folders.hasNext()) { const f=folders.next(); items.push({id:f.getId(),name:f.getName(),mimeType:"application/vnd.google-apps.folder"}); }
  const files = folder.getFiles();
  while (files.hasNext()) { const f=files.next(); items.push({id:f.getId(),name:f.getName(),mimeType:f.getMimeType(),size:f.getSize(),updated:f.getLastUpdated().toISOString()}); }
  items.sort((a,b)=>(a.mimeType.includes("folder")?-1:1)-(b.mimeType.includes("folder")?-1:1)||a.name.localeCompare(b.name));
  return {ok:true,path:folder.getName(),items};
}

function importDriveFile_(fileId) {
  const file=DriveApp.getFileById(fileId);
  const response=UrlFetchApp.fetch(ENDPOINT,{method:"post",headers:{"X-Drive-Token":TOKEN,"X-Drive-File-Id":fileId},payload:{file:file.getBlob().setName(file.getName())},muteHttpExceptions:true});
  const code=response.getResponseCode();
  if(code<200||code>=300)return {ok:false,error:"آرشیو فایل را نپذیرفت: HTTP "+code};
  return Object.assign({ok:true,name:file.getName()},JSON.parse(response.getContentText()||"{}"));
}

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
}

function installHosseinHubTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger("syncHosseinHub").timeBased().everyMinutes(5).create();
  syncHosseinHub();
}
