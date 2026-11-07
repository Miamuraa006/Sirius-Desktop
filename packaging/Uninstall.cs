using System;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Windows.Forms;
using System.Reflection;
[assembly: AssemblyTitle("Sirius Uninstall")]
[assembly: AssemblyProduct("Sirius")]
[assembly: AssemblyVersion("0.5.1.0")]
internal static class UninstallMain {
    [STAThread] static int Main(string[] args) {
        bool silent=args.Contains("/silent");string rootArg=args.FirstOrDefault(x=>x.StartsWith("/root="));
        try {
            if(rootArg==null) {
                string root=Path.GetDirectoryName(Application.ExecutablePath);InstallCore.Validate(root);
                if(!InstallCore.Owned(root))throw new IOException("Не найдена установленная копия Sirius.");
                if(!silent&&MessageBox.Show("Удалить Sirius? Настройки и история останутся в вашем профиле Windows.","Удаление Sirius",MessageBoxButtons.YesNo,MessageBoxIcon.Question)!=DialogResult.Yes)return 0;
                string helper=Path.Combine(Path.GetTempPath(),"SiriusRemove-"+Guid.NewGuid().ToString("N")+".exe");File.Copy(Application.ExecutablePath,helper);
                Process.Start(new ProcessStartInfo(helper,InstallCore.Quote("/root="+root)+" /parent="+Process.GetCurrentProcess().Id+(silent?" /silent":"")){UseShellExecute=false,CreateNoWindow=true});return 0;
            }
            int parent=int.Parse(args.First(x=>x.StartsWith("/parent=")).Substring(8));try{using(var p=Process.GetProcessById(parent))p.WaitForExit(15000);}catch(ArgumentException){}
            InstallCore.Uninstall(rootArg.Substring(6));
            if(!silent)MessageBox.Show("Sirius удалён. Настройки и история сохранены.","Sirius",MessageBoxButtons.OK,MessageBoxIcon.Information);return 0;
        }catch(Exception e){InstallCore.Log(e.ToString());if(!silent)MessageBox.Show(e.Message,"Sirius — удаление не завершено",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
    }
}
