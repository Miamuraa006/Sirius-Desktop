using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;
using System.Reflection;

[assembly: AssemblyTitle("Sirius")]
[assembly: AssemblyDescription("Sirius Desktop — compact assistant")]
[assembly: AssemblyProduct("Sirius Desktop")]
[assembly: AssemblyVersion("0.4.0.0")]
[assembly: AssemblyFileVersion("0.4.0.0")]

internal static class Launcher
{
    // Win32 command-line quoting; arguments never pass through a command shell.
    private static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); }
            else { result.Append('\\', slashes); result.Append(c); }
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        string desktop = AppDomain.CurrentDomain.BaseDirectory;
        string folder = Path.Combine(desktop, "Sirius Desktop");
        string executable = Path.Combine(folder, "app", "Sirius.exe");
        if (!File.Exists(executable))
        {
            MessageBox.Show("Рядом с siruis.exe должна находиться папка Sirius Desktop.\nНе переносите файл отдельно от папки.", "Sirius", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 2;
        }
        try
        {
            var start = new ProcessStartInfo(executable);
            start.WorkingDirectory = folder;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            var commandLine = new StringBuilder();
            foreach (string arg in args) { if (commandLine.Length > 0) commandLine.Append(' '); commandLine.Append(Quote(arg)); }
            start.Arguments = commandLine.ToString();
            using (var child = Process.Start(start))
            {
                // Keep the launcher alive so automated checks get the real exit status.
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception error)
        {
            MessageBox.Show("Не удалось запустить Sirius.\n" + error.Message, "Sirius", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
