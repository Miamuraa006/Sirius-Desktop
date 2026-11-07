using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Collections.Generic;
using System.Diagnostics;
using System.Security.Cryptography;
using Microsoft.Win32;

internal static class InstallCore
{
    internal const string Id = "Sirius.Desktop.7BC09853-14D6-443D-B7FD-7EBEA6C7B218";
    internal const string Version = "0.5.1";
    internal static string Marker(string root) { return Path.Combine(root, ".sirius-install"); }
    internal static string Full(string path) { return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar); }
    internal static string Quote(string s) { return "\"" + s.Replace("\"", "") + "\""; }
    internal static string Key(bool test) { return @"Software\Microsoft\Windows\CurrentVersion\Uninstall\" + (test ? "Sirius.InstallationTest" : "Sirius.Desktop"); }
    internal static string Name(bool test) { return test ? "Sirius (проверка установки)" : "Sirius"; }
    internal static void Log(string message) { File.AppendAllText(Path.Combine(Path.GetTempPath(), "Sirius-Setup.log"), DateTime.Now.ToString("s") + " " + message + Environment.NewLine, Encoding.UTF8); }
    internal static void NoLinks(string path) {
        var d = new DirectoryInfo(path);
        while (d != null) {
            if (d.Exists && (d.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("Папка не должна быть ссылкой: " + d.FullName);
            d = d.Parent;
        }
    }
    internal static string Child(string root, string relative) {
        if (String.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.Contains(":")) throw new IOException("Неверный путь в пакете.");
        string p = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!p.StartsWith(Full(root) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Путь вне папки установки.");
        NoLinks(Path.GetDirectoryName(p));
        if (File.Exists(p) && (File.GetAttributes(p) & FileAttributes.ReparsePoint) != 0) throw new IOException("Файл-ссылка не поддерживается.");
        return p;
    }
    internal static bool Owned(string root) { return File.Exists(Marker(root)) && File.ReadAllLines(Marker(root)).FirstOrDefault() == Id; }
    internal static bool IsTest(string root) { return File.ReadAllLines(Marker(root)).Skip(1).FirstOrDefault() == "test"; }
    internal static void Validate(string root) {
        root = Full(root);
        if (root.StartsWith(@"\\") || root.Length < 10 || root.Length > 120 || root == Full(Path.GetPathRoot(root))) throw new IOException("Выберите обычную локальную папку с коротким путём.");
        NoLinks(root);
        Child(root,".sirius-install"); Child(root,"install.files");
        if (Directory.Exists(root) && Directory.EnumerateFileSystemEntries(root).Any() && !Owned(root)) throw new IOException("Выбранная папка занята другими файлами. Выберите пустую папку Sirius.");
        foreach (var p in Process.GetProcessesByName("Sirius")) {
            try { if (Full(p.MainModule.FileName).StartsWith(root + "\\", StringComparison.OrdinalIgnoreCase)) throw new IOException("Закройте Sirius через меню в трее и повторите установку."); }
            catch (System.ComponentModel.Win32Exception) { }
            finally { p.Dispose(); }
        }
    }
    internal static string Hash(string path) { using (var h = SHA256.Create()) using (var f = File.OpenRead(path)) return BitConverter.ToString(h.ComputeHash(f)).Replace("-", "").ToLowerInvariant(); }
    internal static string[] ShortcutPaths(bool test) { return new[] { Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), Name(test) + ".lnk"), Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), Name(test), "Sirius.lnk") }; }
    internal static void Shortcut(string path, string root) {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        dynamic link = shell.CreateShortcut(path);
        link.TargetPath = Path.Combine(root, "Sirius.exe"); link.WorkingDirectory = root;
        link.IconLocation = Path.Combine(root, "_internal", "ui", "assets", "sirius.ico") + ",0";
        link.Description = "Sirius — помощник рабочего стола"; link.Save();
        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link);
        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
    }
    internal static void Register(string root, bool desktop, bool start, bool test, long bytes) {
        var links = ShortcutPaths(test);
        if (desktop) Shortcut(links[0], root);
        if (start) Shortcut(links[1], root);
        using (var key = Registry.CurrentUser.CreateSubKey(Key(test))) {
            key.SetValue("DisplayName", Name(test)); key.SetValue("DisplayVersion", Version);
            key.SetValue("Publisher", "Altynbek"); key.SetValue("InstallLocation", root);
            key.SetValue("DisplayIcon", Path.Combine(root, "Sirius.exe"));
            key.SetValue("UninstallString", Quote(Path.Combine(root, "Uninstall.exe")));
            key.SetValue("QuietUninstallString", Quote(Path.Combine(root, "Uninstall.exe")) + " /silent");
            key.SetValue("NoModify", 1, RegistryValueKind.DWord); key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            key.SetValue("EstimatedSize", (int)(bytes / 1024), RegistryValueKind.DWord);
        }
    }
    internal static void EmptyDirs(string root, IEnumerable<string> files) {
        var dirs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string file in files) {
            string d = Path.GetDirectoryName(Child(root, file));
            while (d.Length >= root.Length) { dirs.Add(d); if (d.Equals(root, StringComparison.OrdinalIgnoreCase)) break; d = Path.GetDirectoryName(d); }
        }
        foreach (var d in dirs.OrderByDescending(x => x.Length)) { if (Directory.Exists(d) && !Directory.EnumerateFileSystemEntries(d).Any()) Directory.Delete(d); }
    }
    internal static void CleanupStage(string stage) {
        string p = Full(stage), temp = Full(Path.GetTempPath());
        if (!p.StartsWith(temp + "\\", StringComparison.OrdinalIgnoreCase) || !Path.GetFileName(p).StartsWith("SiriusSetup-")) throw new IOException("Неверная временная папка.");
        NoLinks(p);
        if (Directory.Exists(p)) Directory.Delete(p, true);
    }
    internal static void Install(string root, bool desktop, bool start, bool test, Action<int,string> progress) {
        root = Full(root); Validate(root);
        if (Owned(root) && IsTest(root) != test) throw new IOException("Тип установленной копии отличается от пакета.");
        using (var key=Registry.CurrentUser.OpenSubKey(Key(test))) {
            string previous=key==null?null:key.GetValue("InstallLocation") as string;
            if (!String.IsNullOrEmpty(previous) && !String.Equals(Full(previous),root,StringComparison.OrdinalIgnoreCase)) throw new IOException("Sirius уже установлен в другой папке. Сначала удалите его через настройки Windows.");
        }
        string stage = Path.Combine(Path.GetTempPath(), "SiriusSetup-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stage);
        var written = new List<string>(); var restored = new Dictionary<string,string>();
        var metadata = new Dictionary<string,byte[]>();
        foreach (string extra in new[]{".sirius-install","install.files"}) {
            string path=Child(root,extra);metadata[path]=File.Exists(path)?File.ReadAllBytes(path):null;
        }
        foreach (string path in ShortcutPaths(test)) metadata[path]=File.Exists(path)?File.ReadAllBytes(path):null;
        var registryValues=new Dictionary<string,object>();var registryKinds=new Dictionary<string,RegistryValueKind>();
        bool registryExisted;
        using (var key=Registry.CurrentUser.OpenSubKey(Key(test))) {
            registryExisted=key!=null;
            if(key!=null)foreach(string name in key.GetValueNames()){registryValues[name]=key.GetValue(name);registryKinds[name]=key.GetValueKind(name);}
        }
        bool registrationStarted=false;
        bool rootExisted = Directory.Exists(root);
        try {
            var assembly = System.Reflection.Assembly.GetExecutingAssembly();
            string manifest;
            using (var s = assembly.GetManifestResourceStream("files.sha256")) using (var reader = new StreamReader(s, Encoding.UTF8)) manifest = reader.ReadToEnd();
            var expected = new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
            foreach (var line in manifest.Split(new[] {'\r','\n'}, StringSplitOptions.RemoveEmptyEntries)) { var pair = line.Split('\t'); if (pair.Length != 2) throw new IOException("Повреждён список файлов."); expected.Add(pair[1],pair[0]); }
            progress(2, "Проверка и распаковка файлов…");
            long bytes = 0; int index = 0;
            using (var stream = assembly.GetManifestResourceStream("payload.zip")) using (var zip = new ZipArchive(stream, ZipArchiveMode.Read)) {
                if (zip.Entries.Count != expected.Count) throw new IOException("Неверное число файлов пакета.");
                foreach (var entry in zip.Entries) {
                    if (!expected.ContainsKey(entry.FullName)) throw new IOException("Неизвестный файл пакета.");
                    string dst = Child(stage, "files/" + entry.FullName); Directory.CreateDirectory(Path.GetDirectoryName(dst));
                    using (var input = entry.Open()) using (var output = File.Create(dst)) input.CopyTo(output);
                    if (Hash(dst) != expected[entry.FullName]) throw new IOException("Нарушена целостность пакета: " + entry.FullName);
                    bytes += entry.Length; progress(5 + ++index * 60 / expected.Count, "Проверка файлов Sirius…");
                }
            }
            Validate(root); Directory.CreateDirectory(root); index = 0;
            foreach (var relative in expected.Keys) {
                string dst = Child(root, relative);
                if (File.Exists(dst)) { string bak = Child(stage, "backup/" + relative); Directory.CreateDirectory(Path.GetDirectoryName(bak)); File.Copy(dst,bak); restored.Add(dst,bak); }
                Directory.CreateDirectory(Path.GetDirectoryName(dst)); written.Add(relative); File.Copy(Child(stage,"files/"+relative),dst,true);
                progress(65 + ++index * 30 / expected.Count, "Установка Sirius…");
            }
            File.WriteAllLines(Marker(root), new[] { Id, test ? "test" : "normal" }, Encoding.UTF8);
            File.WriteAllLines(Path.Combine(root,"install.files"), expected.Keys, Encoding.UTF8);
            registrationStarted=true; Register(root, desktop, start, test, bytes);
            progress(100,"Sirius установлен"); Log("Installed " + root);
        } catch {
            foreach (string relative in written.AsEnumerable().Reverse()) {
                string dst = Child(root, relative);
                try { if (restored.ContainsKey(dst)) File.Copy(restored[dst],dst,true); else if (File.Exists(dst)) File.Delete(dst); } catch { }
            }
            foreach(var item in metadata) {
                try {if(item.Value!=null){Directory.CreateDirectory(Path.GetDirectoryName(item.Key));File.WriteAllBytes(item.Key,item.Value);}else if(File.Exists(item.Key))File.Delete(item.Key);}catch{}
            }
            if(registrationStarted) {
                try {
                    Registry.CurrentUser.DeleteSubKeyTree(Key(test),false);
                    if(registryExisted)using(var key=Registry.CurrentUser.CreateSubKey(Key(test)))foreach(var item in registryValues)key.SetValue(item.Key,item.Value,registryKinds[item.Key]);
                }catch{}
            }
            if (!rootExisted && Directory.Exists(root)) EmptyDirs(root,written);
            throw;
        } finally { CleanupStage(stage); }
    }
    internal static void Uninstall(string root) {
        root=Full(root); Validate(root);
        if (!Owned(root)) throw new IOException("Папка не принадлежит установщику Sirius.");
        bool test=IsTest(root); string list=Path.Combine(root,"install.files");
        var files=File.ReadAllLines(list).Where(x=>!String.IsNullOrWhiteSpace(x)).ToArray();
        // Validate the entire manifest before removing anything.
        foreach (string relative in files) Child(root,relative);
        foreach (string path in ShortcutPaths(test)) if(File.Exists(path)) {
            dynamic shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell")); dynamic link=shell.CreateShortcut(path);
            bool ours=String.Equals(Full((string)link.TargetPath),Full(Path.Combine(root,"Sirius.exe")),StringComparison.OrdinalIgnoreCase);
            System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link); System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
            if(ours) File.Delete(path);
        }
        string menu=Path.GetDirectoryName(ShortcutPaths(test)[1]); if(Directory.Exists(menu)&&!Directory.EnumerateFileSystemEntries(menu).Any()) Directory.Delete(menu);
        foreach(string relative in files) {string f=Child(root,relative);if(File.Exists(f))File.Delete(f);}
        File.Delete(list); File.Delete(Marker(root)); EmptyDirs(root,files);
        using(var key=Registry.CurrentUser.OpenSubKey(Key(test))) {
            if(key!=null && String.Equals((string)key.GetValue("InstallLocation"),root,StringComparison.OrdinalIgnoreCase)) { key.Close(); Registry.CurrentUser.DeleteSubKeyTree(Key(test),false); }
        }
        Log("Uninstalled " + root + "; user profile preserved");
    }
}
