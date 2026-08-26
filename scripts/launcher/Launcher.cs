using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace AdminEfficiencyPilot
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            try
            {
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string currentDir = Path.Combine(baseDir, "current");
                string runtimePythonw = Path.Combine(currentDir, "runtime", "pythonw.exe");
                string uiScript = Path.Combine(currentDir, "ui.py");
                string dataDir = Path.Combine(baseDir, "data");
                string logsDir = Path.Combine(dataDir, "logs");
                string configPath = Path.Combine(dataDir, "config.json");
                string configExample = Path.Combine(currentDir, "config.json.example");

                if (!Directory.Exists(dataDir))
                {
                    Directory.CreateDirectory(dataDir);
                }
                if (!Directory.Exists(logsDir))
                {
                    Directory.CreateDirectory(logsDir);
                }
                if (!File.Exists(configPath) && File.Exists(configExample))
                {
                    File.Copy(configExample, configPath, false);
                }

                if (!File.Exists(runtimePythonw) || !File.Exists(uiScript))
                {
                    MessageBox.Show(
                        "找不到程式執行核心（current\\runtime\\pythonw.exe 或 current\\ui.py）。\n\n請確認您已將壓縮檔「完整解壓縮」至本機資料夾，而非直接在壓縮檔內開啟執行。",
                        "行政效能領航員 - 啟動錯誤",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error
                    );
                    return;
                }

                ProcessStartInfo startInfo = new ProcessStartInfo
                {
                    FileName = runtimePythonw,
                    Arguments = "-B ui.py",
                    WorkingDirectory = currentDir,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };

                Process.Start(startInfo);
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "啟動過程發生未預期錯誤：\n" + ex.Message,
                    "行政效能領航員 - 錯誤",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }
        }
    }
}
