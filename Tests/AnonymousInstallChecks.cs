using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using CalamusLauncher;
class AnonymousInstallChecks {
 const BindingFlags F=BindingFlags.NonPublic|BindingFlags.Instance;
 static object Call(object o,string n,params object[] args){return o.GetType().GetMethod(n,F).Invoke(o,args);}
 static object Field(object o,string n){return o.GetType().GetField(n,F).GetValue(o);}
 static void Check(bool ok,string message){if(!ok)throw new Exception(message);Console.WriteLine("PASS: "+message);}
 static void Await(Task task){var watch=System.Diagnostics.Stopwatch.StartNew();while(!task.IsCompleted){if(watch.Elapsed.TotalSeconds>180)throw new TimeoutException("Network/install test timeout");var frame=new DispatcherFrame();Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.Background,new Action(()=>frame.Continue=false));Dispatcher.PushFrame(frame);Thread.Sleep(10);}task.GetAwaiter().GetResult();}
 [STAThread]static int Main(){
  MainWindow window=null;
  try{
   var data=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Calamus","LauncherData");Directory.CreateDirectory(data);Directory.CreateDirectory(Path.Combine(Path.GetDirectoryName(data),"Apps"));
   File.WriteAllText(Path.Combine(data,"state-v2.json"),"{\"Apps\":[],\"Categories\":[\"Calamus\"]}");
   File.WriteAllText(Path.Combine(data,"access-v1.json"),"{\"Mode\":\"guest\",\"Repository\":\"CalamusClaro/Calamus-Launcher-Guest\"}");
   // Deliberately unreadable: anonymous operation must not try to decrypt it.
   File.WriteAllText(Path.Combine(data,"github-auth.dpapi"),"invalid-private-token-fixture");
   SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(Dispatcher.CurrentDispatcher));
   window=new MainWindow(false);
   Console.WriteLine("BEGIN: real guest catalogue request");
   var fetch=(Task<RemoteCatalog>)Call(window,"FetchRemoteCatalogAsync",false);Await(fetch);var catalog=fetch.Result;
   Check(catalog.Apps.Count==6&&catalog.Launcher.Version=="0.7.5","guest catalogue loaded anonymously with Transfer and Launcher 0.7.5");
   Call(window,"ApplyHomeCatalog",catalog);var state=(LauncherState)Field(window,"state");
   var package=catalog.Apps.Single(p=>p.Id=="calamus-transfer");
   var app=state.Apps.Single(x=>x.RemoteId==package.Id);
   Check(app.IsUninstalled,"Transfer card appears before installation");
   var download=(Task<string>)Call(window,"DownloadVerifiedZipAsync",package);Await(download);
   string zip=download.Result;
   Check(File.Exists(zip),"anonymous Transfer download and checksum");
   Await((Task)Call(window,"InstallPackageAsync",zip,app,package));
   Check((bool)Call(window,"HasInstalledPayload",app),"Transfer launch entry installed");
   var current=app.Versions.Single(v=>v.Id==app.CurrentId);
   string root=(string)Call(window,"VersionRoot",app,current);
   string exe=Path.Combine(root,current.Entry);
   using(var process=System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(exe,"--smoke"){WorkingDirectory=Path.GetDirectoryName(exe)})){
    Check(process.WaitForExit(25000)&&process.ExitCode==0,"installed WPF application launches");
   }
   string marker=Path.Combine(root,"HostVersion.txt");
   File.WriteAllText(marker,"0.0.9");
   Check(Call(window,"AvailableHomeUpdate",app)==package,"a previous installed version offers an update");
   Await((Task)Call(window,"InstallPackageAsync",zip,app,package));
   Check(Call(window,"AvailableHomeUpdate",app)==null&&app.RemoteVersion=="0.1.0","applying the actual package clears the update offer");
   Call(window,"UninstallManagedAppCore",app);
   Check(!(bool)Call(window,"HasInstalledPayload",app)&&app.IsUninstalled&&!File.Exists(exe),"uninstall removes Transfer binaries and keeps its card");
   File.Delete(zip);
   Check(File.ReadAllText(Path.Combine(data,"github-auth.dpapi"))=="invalid-private-token-fixture","guest never consumed or changed stored author credentials");
   Console.WriteLine("PASS: real guest Transfer download, installation, launch, update and uninstall");return 0;
  }catch(Exception ex){Console.WriteLine(ex);return 1;}
  finally{if(window!=null)Call(window,"ExitApp");}
 }
}
