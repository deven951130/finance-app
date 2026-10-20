; =====================================================================
; Windows 安裝程式設定檔（Inno Setup）
;
; 做什麼：把 installer\build_runtime.py 準備好的 dist\FinanceApp 資料夾
;        （官方嵌入式 Python + 套件 + 理財系統程式碼），包成一個
;        FinanceApp-Setup-版本.exe。使用者點兩下就會出現安裝精靈，
;        裝好後開始選單和桌面都有捷徑，也可以在「設定 > 應用程式」解除安裝。
;
; 為什麼不是 PyInstaller 的 FinanceApp.exe：沒有數位簽章的 exe 會被部分防毒軟體
; （例如 Trend Micro）直接刪掉，捷徑點了沒反應。捷徑改成執行官方有簽章的 pythonw.exe，
; 詳細原因見 installer\build_runtime.py 最上面的說明。
;
; 怎麼用：一般不用自己跑，build_exe.bat 會自動呼叫。
;        手動執行：先跑 python installer\build_runtime.py，再執行
;        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\FinanceApp.iss
; 結果：dist\installer\FinanceApp-Setup-1.0.0.exe
;
; 資料安全：安裝程式只包含「程式」，不包含資料庫。
;          資料庫在 C:\Users\你的名字\FinanceApp\finance.db（見 db.py），
;          不在安裝資料夾裡，所以更新、重新安裝、解除安裝都不會刪掉你的資料。
;
; 注意：這個檔案要存成「UTF-8 含 BOM」，Inno Setup 才讀得懂中文。
; =====================================================================

; 版本號。打包時可以用 ISCC /DAppVersion=1.2.0 覆蓋
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
; AppId 是這個軟體的「身分證字號」，Windows 用它判斷是不是同一個軟體。
; 一旦發佈就不要改：改了之後，新版會被當成另一個軟體，舊版不會被更新掉。
AppId={{2F2A5615-5C5E-448E-840C-AF74F38647C0}
AppName=個人理財管理系統
AppVersion={#AppVersion}
AppPublisher=deven951130
AppPublisherURL=https://github.com/deven951130/finance-app
; 安裝到「只有自己這個帳號」的位置（C:\Users\你的名字\AppData\Local\Programs\FinanceApp），
; 這樣不需要系統管理員權限，安裝時不會跳出「是否允許變更」的視窗。
PrivilegesRequired=lowest
DefaultDirName={autopf}\FinanceApp
DefaultGroupName=個人理財管理系統
; 開始選單資料夾名稱固定，不讓使用者改，少一個步驟
DisableProgramGroupPage=yes
; 打包出來的程式是 64 位元的
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 輸出位置（相對於這個 .iss 檔所在的 installer 資料夾）
OutputDir=..\dist\installer
OutputBaseFilename=FinanceApp-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName=個人理財管理系統
; lzma2 + solid：壓縮率最好，約 280 MB 的程式可以壓到 100 MB 以下
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
; 繁體中文介面。這個語言檔來自 Inno Setup 官方 repo，放在 installer 資料夾，
; 這樣不管電腦上裝的 Inno Setup 有沒有附中文都能用（需要 Inno Setup 6.5 以上）。
Name: "chinesetraditional"; MessagesFile: "ChineseTraditional.isl"

[Tasks]
; 安裝精靈裡的勾選框，預設打勾
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "其他選項："

[InstallDelete]
; 更新版本時，先刪掉舊版的程式，避免新舊檔案混在一起出錯。這些資料夾裡只有程式，沒有你的資料。
; _internal 和 FinanceApp.exe 是以前 PyInstaller 版留下的
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\FinanceApp.exe"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"

[UninstallDelete]
; Python 第一次執行時會自己產生 __pycache__（加快下次啟動），不是安裝進去的檔案，
; 解除安裝時要另外指定刪掉，不然會留下空的資料夾
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"

[Files]
; 把 build_runtime.py 準備好的整個資料夾複製到安裝位置
Source: "..\dist\FinanceApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 捷徑執行「pythonw.exe run_app.py」（pythonw = 沒有黑色視窗的 python）。
; IconFilename：捷徑用理財系統的圖示，不是 Python 的。
; AppUserModelID：和 run_app.py 的 APP_ID 一樣，工作列才會顯示理財系統的圖示、不和其他 Python 程式擠在一起。
; 開始選單
Name: "{group}\個人理財管理系統"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\run_app.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\icon.ico"; AppUserModelID: "deven951130.FinanceApp"; Comment: "記帳、預算、負債與持股管理"
Name: "{group}\解除安裝 個人理財管理系統"; Filename: "{uninstallexe}"
; 桌面（只有勾選「建立桌面捷徑」時才建立）
Name: "{autodesktop}\個人理財管理系統"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\run_app.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\icon.ico"; AppUserModelID: "deven951130.FinanceApp"; Tasks: desktopicon

[Run]
; 安裝完成的最後一頁，提供「立即啟動」的勾選框
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\run_app.py"""; WorkingDir: "{app}\app"; Description: "立即啟動 個人理財管理系統"; Flags: nowait postinstall skipifsilent

[Code]
// 解除安裝完成後提醒：資料沒有被刪掉，在哪裡
// （Inno Setup 的 [Code] 區段是 Pascal 語法，註解用 // ）
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    MsgBox('程式已移除。' + #13#10 + #13#10 +
           '你的理財資料仍保留在：' + #13#10 +
           ExpandConstant('{%USERPROFILE}') + '\FinanceApp\finance.db' + #13#10 + #13#10 +
           '如果確定不再需要，可以自己刪除那個資料夾。',
           mbInformation, MB_OK);
end;
