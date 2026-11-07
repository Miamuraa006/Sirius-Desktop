using System;
using System.IO;
using System.Linq;
using System.Drawing;
using System.Diagnostics;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Reflection;
[assembly: AssemblyTitle("Sirius Setup")]
[assembly: AssemblyProduct("Sirius")]
[assembly: AssemblyCompany("Altynbek")]
[assembly: AssemblyVersion("0.5.1.0")]
[assembly: AssemblyFileVersion("0.5.1.0")]

internal static class SetupMain {
    [STAThread] static int Main(string[] args) {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        if(!Environment.Is64BitOperatingSystem) {MessageBox.Show("Требуется Windows 10/11 x64.","Sirius");return 1;}
        bool silent=args.Contains("/silent"), test=args.Contains("/test");
        string dir=args.FirstOrDefault(x=>x.StartsWith("/dir=",StringComparison.OrdinalIgnoreCase));
        dir=dir==null?Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","Sirius"):dir.Substring(5);
        try {
            if(silent) {InstallCore.Install(dir,!args.Contains("/nodesktop"),!args.Contains("/nostart"),test,(p,s)=>{});return 0;}
            Application.Run(new SetupForm(dir));return 0;
        } catch(Exception e) {InstallCore.Log(e.ToString());if(!silent)MessageBox.Show(e.Message,"Sirius — установка не завершена",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
    }
}
internal sealed class SetupForm : Form {
    int page=0; bool busy=false; Panel content=new Panel(); Button next=new Button(),back=new Button(),cancel=new Button();
    TextBox folder=new TextBox(); CheckBox desktop=new CheckBox(),start=new CheckBox(),launch=new CheckBox();
    Label heading=new Label(),status=new Label(); ProgressBar progress=new ProgressBar();
    float uiScale=1;
    int Px(int value) {return (int)Math.Round(value*uiScale);}
    void Place(Control c,int x,int y,int w,int h) {c.SetBounds(Px(x),Px(y),Px(w),Px(h));}
    readonly Color muted=Color.FromArgb(160,173,193),accent=Color.FromArgb(70,145,220);
    public SetupForm(string dir) {
        AutoScaleMode=AutoScaleMode.None;using(var graphics=CreateGraphics())uiScale=graphics.DpiX/96f;
        Text="Установка Sirius"; ClientSize=new Size(Px(650),Px(465)); FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;StartPosition=FormStartPosition.CenterScreen;
        Font=new Font("Segoe UI",10);BackColor=Color.FromArgb(14,18,26);ForeColor=Color.FromArgb(235,242,250);
        Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        var logo=new PictureBox {SizeMode=PictureBoxSizeMode.Zoom};Place(logo,28,25,60,60);
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("brand.png")) { if(stream!=null)using(var original=Image.FromStream(stream))logo.Image=new Bitmap(original,120,120);else logo.Image=Icon.ToBitmap(); } Controls.Add(logo);
        Place(heading,108,23,505,45);heading.Font=new Font("Segoe UI Semibold",21);Controls.Add(heading);
        var subtitle=Label("Помощник рабочего стола · 0.5.1",108,68,490,25);subtitle.ForeColor=muted;Controls.Add(subtitle);
        Place(content,30,115,590,265);Controls.Add(content);
        Place(next,490,407,130,34);Place(back,350,407,130,34);Place(cancel,30,407,120,34);
        foreach(var button in new[]{next,back,cancel}) {button.FlatStyle=FlatStyle.Flat;button.FlatAppearance.BorderColor=Color.FromArgb(66,79,99);button.BackColor=Color.FromArgb(29,37,51);button.ForeColor=ForeColor;Controls.Add(button);}
        next.BackColor=accent;next.Click+=async(s,e)=>{if(page==3)await Install();else if(page==5){if(launch.Checked)Process.Start(new ProcessStartInfo(Path.Combine(folder.Text,"Sirius.exe")){WorkingDirectory=folder.Text,UseShellExecute=true});Close();}else{if(page==1){try{InstallCore.Validate(folder.Text);}catch(Exception ex){MessageBox.Show(this,ex.Message,"Sirius");return;}}page++;Render();}};
        back.Text="← Назад";back.Click+=(s,e)=>{page--;Render();};cancel.Text="Отмена";cancel.Click+=(s,e)=>Close();
        FormClosing+=(s,e)=>{if(busy)e.Cancel=true;};
        folder.Text=dir;desktop.Text="Создать ярлык Sirius на рабочем столе";start.Text="Добавить Sirius в меню «Пуск»";launch.Text="Запустить Sirius";
        desktop.Checked=start.Checked=launch.Checked=true;Render();
    }
    Label Label(string text,int x,int y,int w,int h) {var label=new Label{Text=text,ForeColor=ForeColor,AutoSize=false};Place(label,x,y,w,h);return label;}
    void Render() {
        content.Controls.Clear();back.Visible=page>0&&page<4;cancel.Visible=page<4;next.Enabled=true;
        next.Text=page==3?"Установить":page==5?"Готово":"Далее  →";
        if(page==0) {heading.Text="Добро пожаловать в Sirius";content.Controls.Add(Label("Голос, чат и управление компьютером.\n\nSirius работает локально: модель распознавания уже входит в пакет. Python отдельно устанавливать не нужно.\n\nМастер поможет выбрать папку и создать ярлыки. Установка выполняется для текущего пользователя.",0,8,585,200));}
        if(page==1) {heading.Text="Папка установки";content.Controls.Add(Label("Куда установить Sirius?",0,5,580,28));Place(folder,0,47,475,30);folder.BackColor=Color.FromArgb(27,35,48);folder.ForeColor=ForeColor;content.Controls.Add(folder);var browse=new Button{Text="Обзор…",Location=new Point(Px(485),Px(45)),Size=new Size(Px(100),Px(32))};browse.Click+=(s,e)=>{using(var d=new FolderBrowserDialog()){d.SelectedPath=folder.Text;d.Description="Папка для Sirius";if(d.ShowDialog(this)==DialogResult.OK)folder.Text=d.SelectedPath;}};content.Controls.Add(browse);content.Controls.Add(Label("Нужно около 650 МБ для программы и место для временной распаковки.\n\nНастройки и история будут храниться отдельно в вашем профиле Windows.",0,105,580,125));}
        if(page==2) {heading.Text="Ярлыки";Place(desktop,0,20,580,34);Place(start,0,67,580,34);content.Controls.Add(desktop);content.Controls.Add(start);content.Controls.Add(Label("На ярлыках будет название Sirius и новая иконка.\nАвтозапуск с Windows не включается.",0,140,580,65));}
        if(page==3) {heading.Text="Всё готово к установке";content.Controls.Add(Label("Папка:\n"+folder.Text+"\n\nРабочий стол: "+(desktop.Checked?"создать ярлык":"без ярлыка")+"\nМеню «Пуск»: "+(start.Checked?"создать ярлык":"без ярлыка")+"\n\nНажмите «Установить», чтобы продолжить.",0,8,585,240));}
        if(page==4) {heading.Text="Установка Sirius";Place(status,0,35,580,40);content.Controls.Add(status);Place(progress,0,95,580,24);content.Controls.Add(progress);next.Enabled=false;}
        if(page==5) {heading.Text="Sirius установлен";content.Controls.Add(Label("Всё готово.\n\nНажмите Alt + M или скажите «Сириус».\nНапишите help, чтобы посмотреть возможности.\n\nУдаление доступно через «Установленные приложения» Windows. Ваши данные сохраняются отдельно.",0,0,580,183));Place(launch,0,207,580,32);content.Controls.Add(launch);}
    }
    async Task Install() {
        page=4;busy=true;Render();string dir=folder.Text;bool desk=desktop.Checked,menu=start.Checked;
        try {await Task.Run(()=>InstallCore.Install(dir,desk,menu,false,(percent,message)=>BeginInvoke(new Action(()=>{progress.Value=percent;status.Text=message;}))));page=5;}
        catch(Exception e) {InstallCore.Log(e.ToString());MessageBox.Show(this,e.Message,"Sirius — установка не завершена",MessageBoxButtons.OK,MessageBoxIcon.Error);page=3;}
        finally {busy=false;Render();}
    }
}
