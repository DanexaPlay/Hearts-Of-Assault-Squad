"""User-run progress window. Never activates a window or sends game input."""
import argparse,ctypes,time,subprocess,sys
from ctypes import wintypes as W
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from .core import ROOT,read_json,write_json


def run(path,parent):
    root=tk.Tk();root.withdraw();root.overrideredirect(True)
    root.configure(bg='#17212f');root.geometry('440x184+30+30')
    area=tk.Frame(root,bg='#17212f',padx=20,pady=15);area.pack(fill='both',expand=True)
    tk.Label(area,text='HOI4 × MEN OF WAR',bg='#17212f',fg='#91a5bd',font=('Segoe UI',9,'bold')).pack(anchor='w')
    title=tk.Label(area,text='',bg='#17212f',fg='white',font=('Segoe UI',14,'bold'));title.pack(anchor='w',pady=(8,4))
    detail=tk.Label(area,text='',bg='#17212f',fg='#ced7e2',wraplength=398,justify='left',font=('Segoe UI',10));detail.pack(anchor='w')
    bar=ttk.Progressbar(area,mode='indeterminate',length=398);bar.pack(fill='x',pady=(12,5))
    footer=tk.Label(area,text='',bg='#17212f',fg='#91a5bd',font=('Segoe UI',9));footer.pack(anchor='w')
    close=tk.Button(area,text='Закрыть',command=root.destroy,bg='#29384a',fg='white',relief='flat')
    def cancel_unfinished():
        subprocess.Popen([sys.executable,'-m','bridge.cancel_transition','--restart'],cwd=ROOT,creationflags=0x00000010)
        root.destroy()
    cancel_button=tk.Button(area,text='Отменить незавершённый бой',command=cancel_unfinished,
        bg='#36557b',fg='white',relief='flat',padx=10,pady=5)
    root.update_idletasks()
    api=ctypes.WinDLL('user32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    api.GetAncestor.argtypes=[W.HWND,W.UINT];api.GetAncestor.restype=W.HWND
    getstyle=api.GetWindowLongPtrW;setstyle=api.SetWindowLongPtrW
    getstyle.argtypes=[W.HWND,ctypes.c_int];getstyle.restype=ctypes.c_ssize_t
    setstyle.argtypes=[W.HWND,ctypes.c_int,ctypes.c_ssize_t];setstyle.restype=ctypes.c_ssize_t
    api.SetWindowPos.argtypes=[W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT]
    api.EnableWindow.argtypes=[W.HWND,W.BOOL]
    api.GetForegroundWindow.restype=W.HWND
    handle=api.GetAncestor(root.winfo_id(),2)
    # Install NOACTIVATE before mapping; merely showing this panel must never
    # make the existing exact-game foreground guard fail.
    style=getstyle(handle,-20)
    setstyle(handle,-20,(style|0x08000000|0x00000080)&~0x00040000)
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD
    kernel.CloseHandle.argtypes=[W.HANDLE]
    parent_handle=kernel.OpenProcess(0x100000,False,parent)
    if not parent_handle:root.destroy();return
    shown=False;animated=False;last=None;message={}
    def tick():
        nonlocal shown,animated,last,message
        try:
            current=read_json(path)
            if current!=last:
                message=current;last=current
                title.config(text=current.get('title',''))
                detail.config(text=current.get('user_error') or current.get('detail',''))
                if current.get('phase') in ('error','rejected'):
                    if current.get('action')=='cancel_unfinished':cancel_button.pack(anchor='w',pady=(10,0))
                    else:cancel_button.pack_forget()
                    close.pack(anchor='e',pady=8)
                else:close.pack_forget();cancel_button.pack_forget()
                height=300 if current.get('phase') in ('error','rejected') else 184
                x=max(12,root.winfo_screenwidth()-464);y=max(12,root.winfo_screenheight()-height-64)
                root.geometry(f'440x{height}+{x}+{y}')
        except (OSError,ValueError):pass
        now=time.time_ns()
        parent_dead=parent_handle and kernel.WaitForSingleObject(parent_handle,0)==0
        error=message.get('phase') in ('error','rejected')
        if parent_dead and not error:root.destroy();return
        visible=message.get('visible',False) and (error or now<message.get('hide_after_ns',now+1))
        if visible and not shown:
            root.update_idletasks()
            height=300 if error else 184
            x=max(12,root.winfo_screenwidth()-464);y=max(12,root.winfo_screenheight()-height-64)
            root.geometry(f'440x{height}+{x}+{y}')
            before=api.GetForegroundWindow()
            # Tk may explicitly request activation while deiconifying. A
            # temporarily disabled HWND cannot acquire keyboard focus.
            api.EnableWindow(handle,False)
            root.deiconify()
            api.SetWindowPos(handle,W.HWND(-1),x,y,440,height,0x0010|0x0040)
            api.EnableWindow(handle,True)
            write_json(path.with_suffix('.window.json'),{'shown_at_ns':now,'no_activate_style':bool(getstyle(handle,-20)&0x08000000),
                'foreground_before':before,'foreground_after':api.GetForegroundWindow(),
                'foreground_unchanged':before==api.GetForegroundWindow()})
            shown=True
        elif not visible and shown:root.withdraw();shown=False
        busy=visible and message.get('busy',False)
        if busy and not animated:bar.start(14);animated=True
        elif not busy and animated:bar.stop();animated=False
        if visible:
            seconds=max(0,(now-message.get('started_at_ns',now))//1_000_000_000)
            footer.config(text=f'Ожидание: {seconds} сек.' if busy else '')
        root.after(150,tick)
    root.after(0,tick)
    try:root.mainloop()
    finally:
        if parent_handle:kernel.CloseHandle(parent_handle)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--state',type=Path,required=True);parser.add_argument('--parent',type=int,required=True)
    args=parser.parse_args();run(args.state,args.parent)
