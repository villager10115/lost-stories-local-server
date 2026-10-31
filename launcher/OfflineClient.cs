using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

class OfflineClient : Form {
    TextBox output = new TextBox();
    Button start = new Button();
    Button verify = new Button();
    Process worker;
    string root = AppDomain.CurrentDomain.BaseDirectory;
    public OfflineClient() {
        Text = "Lost Stories 本地离线客户端";
        Width = 780; Height = 480;
        start.Text = "启动游戏"; start.SetBounds(12, 12, 130, 36);
        verify.Text = "校验完整文件"; verify.SetBounds(154, 12, 150, 36);
        Button saves = new Button(); saves.Text = "打开存档目录"; saves.SetBounds(316, 12, 150, 36);
        output.Multiline = true; output.ReadOnly = true; output.ScrollBars = ScrollBars.Vertical;
        output.SetBounds(12, 60, 740, 365); output.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        output.Text = "无需 DMM。存档位于本目录 data；换机请复制整个文件夹。\r\n当前玩法实现范围见 reports\\FLOW_COVERAGE.md。\r\n";
        Controls.AddRange(new Control[] {start, verify, saves, output});
        start.Click += delegate {Run("");}; verify.Click += delegate {Run("--verify");};
        saves.Click += delegate {Process.Start("explorer.exe", Quote(Path.Combine(root, "data")));};
        FormClosing += delegate(object s, FormClosingEventArgs e) {
            if (worker != null && !worker.HasExited) {
                e.Cancel = true;
                MessageBox.Show("请先正常退出游戏，或等待文件校验完成。", Text);
            }
        };
    }
    static string Quote(string text) {return "\"" + text.Replace("\"", "\\\"") + "\"";}
    ProcessStartInfo Info(string args) {
        ProcessStartInfo info = new ProcessStartInfo(Path.Combine(root, "runtime", "python", "python.exe"),
            "-u " + Quote(Path.Combine(root, "launcher", "portable_launcher.py")) + " " + args);
        info.WorkingDirectory = root; info.UseShellExecute = false; info.CreateNoWindow = true;
        info.RedirectStandardOutput = true; info.RedirectStandardError = true;
        info.StandardOutputEncoding = Encoding.UTF8; info.StandardErrorEncoding = Encoding.UTF8;
        info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        return info;
    }
    void Append(string line) {
        if (line != null && !IsDisposed) BeginInvoke((Action)(() => output.AppendText(line + "\r\n")));
    }
    void Run(string args) {
        try {
            start.Enabled = verify.Enabled = false;
            worker = new Process(); worker.StartInfo = Info(args); worker.EnableRaisingEvents = true;
            worker.OutputDataReceived += (s,e) => Append(e.Data);
            worker.ErrorDataReceived += (s,e) => Append(e.Data);
            worker.Exited += delegate {BeginInvoke((Action)(() => {
                output.AppendText("完成，退出码 " + worker.ExitCode + "\r\n");
                start.Enabled = verify.Enabled = true;
            }));};
            worker.Start(); worker.BeginOutputReadLine(); worker.BeginErrorReadLine();
        } catch (Exception ex) {start.Enabled = verify.Enabled = true; MessageBox.Show(ex.Message, Text);}
    }
    [STAThread] static int Main(string[] args) {
        Application.EnableVisualStyles();
        OfflineClient form = new OfflineClient();
        if (args.Length == 1 && (args[0] == "--verify" || args[0] == "--smoke")) {
            using (Process p = Process.Start(form.Info(args[0]))) {
                string log = p.StandardOutput.ReadToEnd(); string err = p.StandardError.ReadToEnd(); p.WaitForExit();
                File.WriteAllText(Path.Combine(form.root, "logs", "exe-check.log"), log + err, Encoding.UTF8);
                return p.ExitCode;
            }
        }
        Application.Run(form); return 0;
    }
}
