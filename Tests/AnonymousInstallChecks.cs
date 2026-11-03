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
   window=new MainWindow(false);
   var fetch=(Task<RemoteCatalog>)Call(window,"FetchRemoteCatalogAsync",false);Await(fetch);var catalog=fetch.Result;
   Check(catalog.Apps.Count==5&&catalog.Launcher.Version=="0.6.0","public catalogue loaded anonymously with five apps and Launcher 0.6.0");
   Call(window,"ApplyHomeCatalog",catalog);var state=(LauncherState)Field(window,"state");
   Check(state.Apps.Count==5&&state.Apps.All(a=>a.IsUninstalled),"fresh guest sees five installable cards");
   foreach(var package in catalog.Apps.Concat(new[]{catalog.Launcher})){
    var download=(Task<string>)Call(window,"DownloadVerifiedZipAsync",package);Await(download);string zip=download.Result;
    Check(File.Exists(zip),"anonymous verified download: "+package.Id);
    if(package.Id!="calamus-launcher"){
     var app=state.Apps.Single(a=>a.RemoteId==package.Id);
     Await((Task)Call(window,"InstallPackageAsync",zip,app,package));
     Check((bool)Call(window,"HasInstalledPayload",app),"installed launch entry exists: "+package.Id);
    }
    File.Delete(zip);
   }
   var saved=new System.Web.Script.Serialization.JavaScriptSerializer().Deserialize<LauncherState>(File.ReadAllText(Path.Combine(data,"state-v2.json")));
   Check(saved.Apps.Count==5&&saved.Apps.All(a=>!a.IsUninstalled&&!string.IsNullOrEmpty(a.CurrentId)),"all five installed records persisted");
   Check(File.ReadAllText(Path.Combine(data,"github-auth.dpapi"))=="invalid-private-token-fixture","guest never consumed or changed stored author credentials");
   Console.WriteLine("PASS: real anonymous guest catalogue, six downloads, five installations");return 0;
  }catch(Exception ex){Console.WriteLine(ex);return 1;}
  finally{if(window!=null)Call(window,"ExitApp");}
 }
}
