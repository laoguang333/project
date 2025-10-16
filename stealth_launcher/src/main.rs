use std::process::Command;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

fn main() {
    // 创建一个不显示窗口的进程来执行Python命令
    let mut cmd = Command::new("python");
    cmd.arg("-m")
       .arg("stealth_monitor.qt_finplot");
    
    // Windows平台特定设置：不显示控制台窗口
    #[cfg(windows)]
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW flag on Windows

    // 尝试启动进程
    match cmd.spawn() {
        Ok(_) => {
            // 进程成功启动，立即退出此程序
            std::process::exit(0);
        }
        Err(e) => {
            // 如果启动失败，记录错误并退出
            eprintln!("Failed to start stealth_monitor: {}", e);
            std::process::exit(1);
        }
    }
}
