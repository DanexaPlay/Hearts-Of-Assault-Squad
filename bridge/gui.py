"""Local desktop interface; no network service or external dependencies."""
import tkinter as tk
import shutil
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk,filedialog,messagebox,simpledialog
from pathlib import Path
from .core import config,read_json,write_json,Ledger,BridgeError,vanilla_data_compatible,archive_result_evidence
from .gem import generate,parse_result
from .hoi import read_campaign,export_combat,vanilla_metadata
from .commands import write_apply_files

def run():
    app=tk.Tk(); app.title('HOI4 × Men of War — экспериментальный мост'); app.geometry('820x760')
    frame=ttk.Frame(app,padding=20); frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Перенести только выбранное сражение',font=('Segoe UI',17)).pack(anchor='w')
    ttk.Label(frame,text='Пока вы не выбрали бой, HOI4 рассчитывает все сражения обычным образом.').pack(anchor='w',pady=8)
    ttk.Label(frame,text='Полный состав, очки и таймер проверены. Автоматический переход сейчас проходит проверку.',foreground='#a44').pack(anchor='w')
    status=tk.Text(frame,height=17,wrap='word'); status.pack(fill='both',expand=True,pady=12)
    state={}
    def show(text): status.insert('end',str(text)+'\n'); status.see('end')
    def guarded(action):
        def f():
            try: action()
            except Exception as e: messagebox.showerror('Мост остановлен',str(e)); show(e)
        return f
    def prepare(b):
        folder=filedialog.askdirectory(title='Новая папка для этого боя')
        if not folder: return
        path=Path(folder)
        if (path/'ledger.sqlite').exists(): raise BridgeError('Выберите новую папку; этот бой уже зарегистрирован')
        report=generate(b,config(),path); Ledger(path/'ledger.sqlite').register(b)
        state['path']=path
        show(f"Создана миссия: {report['actors']} бойцов и единиц техники. Карта: {report['map']}.")
        if (path/'formations.json').exists():
            for side in ('attacker','defender'):
                parts=[x for x in read_json(path/'formations.json') if x['side']==side]
                show(('Атакующие' if side=='attacker' else 'Защитники')+': '+', '.join(x['component']['type'] for x in parts))
        if report['warning']: show('Приближение местности: '+report['warning'])
        show('Миссия создана на существующей карте. Откройте её в редакторе Men of War. HOI4 должна оставаться на паузе.')
    def export_saved():
        filename=filedialog.askopenfilename(title='Сохранение HOI4, сделанное на паузе',filetypes=[('HOI4 save','*.hoi4')])
        if not filename: return
        show('Читаю сохранение…'); app.update_idletasks()
        campaign=read_campaign(filename)
        if campaign['speed']!='0': raise BridgeError('Сохраните кампанию на паузе перед переносом боя')
        if not campaign['combats']: raise BridgeError('В сохранении нет активных наземных сражений')
        picker=tk.Toplevel(app); picker.title('Выберите конкретное сражение'); picker.geometry('780x420')
        listing=tk.Listbox(picker); listing.pack(fill='both',expand=True,padx=12,pady=12)
        combats=[c for c in campaign['combats'] if not campaign.get('player_country') or any(d['country']==campaign['player_country'] for side in ('attacker','defender') for d in c[side])]
        if not combats: picker.destroy(); raise BridgeError('У страны игрока нет активных наземных сражений')
        for c in combats:
            tags=lambda side: ', '.join(sorted({d['country'] for d in c[side]}))
            listing.insert('end',f"{c['combat_id']} — провинция {c['province']}: {tags('attacker')} → {tags('defender')} ({len(c['attacker'])} / {len(c['defender'])} див.)")
        def select():
            indices=listing.curselection()
            if not indices: return
            combat=combats[indices[0]]
            metadata=None
            if vanilla_data_compatible(campaign.get('mods')):
                metadata=vanilla_metadata(campaign,combat['province'],config()['hoi4'])
                state_id=metadata['state']; terrain=metadata['terrain']
                show(f"Местность прочитана из игры: {terrain}, регион {state_id}")
            else:
                state_id=simpledialog.askinteger('Регион HOI4','ID региона сражения (учитывайте моды):',parent=picker,minvalue=1)
                if state_id is None: return
                terrain=simpledialog.askstring('Ландшафт','Тип: plains, forest, hills, mountain, urban, desert, marsh, jungle',parent=picker)
                if not terrain: return
            river=messagebox.askyesno('Переправа','Атака проходит через реку?',parent=picker)
            b=export_combat(campaign,combat['combat_id'],state_id,terrain.strip().lower(),river)
            if metadata:
                b['metadata_source']=metadata['source'];b['weather']=metadata.get('weather',b['weather'])
            picker.destroy(); prepare(b)
        ttk.Button(picker,text='Симулировать выбранное сражение в Men of War',command=guarded(select)).pack(fill='x',padx=12,pady=12)
    def export():
        filename=filedialog.askopenfilename(title='Выберите описание конкретного боя',filetypes=[('Battle JSON','*.json')])
        if not filename: return
        b=read_json(filename)
        if not messagebox.askokcancel('Пауза перед тактическим боем','Поставьте HOI4 на паузу и создайте отдельное сохранение. Продолжить экспорт выбранного боя?'): return
        prepare(b)
    def session():
        folder=filedialog.askdirectory(title='Папка экспортированного боя')
        if folder: state['path']=Path(folder); show('Сессия: '+folder)
    def result():
        path=state['path']; progress=Path(config()['mow_progress'])
        mixed=any(a['kind']!='infantry' for a in read_json(path/'roster.json'))
        filename=filedialog.askopenfilename(title='mission.scn из сохранения завершённого боя MoW' if mixed else 'Результат завершённой миссии MoW',initialdir=str(progress.parent/'save' if mixed else progress.parent),initialfile='mission.scn' if mixed else progress.name,filetypes=[('Состояние миссии','*.scn'),('Пехотные итоги','*.set'),('Все файлы','*')])
        if not filename: return
        r=parse_result(read_json(path/'battle.json'),read_json(path/'roster.json'),filename)
        r=archive_result_evidence(r,path)
        write_json(path/'result.json',r)
        show('Победитель: '+('атакующая сторона' if r['winner']=='attacker' else 'защитники'))
        for side,label in [('attacker','Атакующие'),('defender','Защитники')]:
            show(f"{label}: переносу соответствует {sum(x['manpower_lost'] for x in r['losses'][side])} потерь личного состава HOI4.")
    def stage():
        path=state['path']; b=read_json(path/'battle.json')
        current_save=None
        if b.get('source')=='hoi4_text_save':
            messagebox.showinfo('Проверка кампании','Оставьте HOI4 на паузе и создайте текущее сохранение. Его дата, участники и состояние дивизий должны совпасть с экспортом.')
            current_save=filedialog.askopenfilename(title='Текущее сохранение HOI4 для проверки перед применением',filetypes=[('HOI4 save','*.hoi4')])
            if not current_save: return
        command=Ledger(path/'ledger.sqlite').stage(b,read_json(path/'result.json'),current_save)
        batch,run_command=write_apply_files(path,b,command)
        app.clipboard_clear(); app.clipboard_append(run_command)
        show('Подготовлен файл: '+str(batch))
        show('Скопируйте этот файл в папку установленной HOI4: '+config()['hoi4'])
        show('Короткая команда скопирована: '+run_command)
        show('После выполнения команды подтвердите результат по журналу HOI4. Не вставляйте длинный эффект вручную в строку консоли.')
    def acknowledge():
        path=state['path']; log=Path(config()['hoi4_user'])/'logs/game.log'
        filename=filedialog.askopenfilename(title='Журнал HOI4 после выполнения команды',initialdir=str(log.parent),initialfile=log.name)
        if not filename: return
        b=read_json(path/'battle.json'); Ledger(path/'ledger.sqlite').acknowledge(b['id'],filename)
        show('HOI4 записала подтверждение применения. Этот результат помечен как применённый.')
    def prepare_copy():
        path=state['path']; b=read_json(path/'battle.json'); r=read_json(path/'result.json')
        source=filedialog.askopenfilename(title='Текущая кампания на паузе, совпадающая с экспортом',filetypes=[('HOI4 save','*.hoi4')])
        if not source: return
        retreats={}
        if r['winner']=='attacker':
            from .save_import import retreat_candidates
            options=retreat_candidates(b,source)
            for d in b['defender']['divisions']:
                choices=options[d['id']]
                if not choices: raise BridgeError('Нет безопасной соседней провинции для отступления: '+d['name'])
                if len(choices)==1: retreats[d['id']]=choices[0]
                else:
                    target=simpledialog.askinteger('Отступление',d['name']+' — выберите провинцию из: '+', '.join(map(str,choices)),parent=app)
                    if target is None: return
                    if target not in choices: raise BridgeError('Выбранная провинция недоступна для отступления')
                    retreats[d['id']]=target
        output=filedialog.asksaveasfilename(title='Отдельное новое сохранение с результатом',initialdir=str(Path(config()['hoi4_user'])/'save games'),initialfile='HMB_'+b['id'][:8]+'.hoi4',defaultextension='.hoi4',filetypes=[('HOI4 save','*.hoi4')])
        if not output: return
        show('Проверяю кампанию и создаю отдельную копию…'); app.update_idletasks()
        report=Ledger(path/'ledger.sqlite').prepare_save(b,r,source,output,retreats)
        write_json(path/'prepared_save.json',report)
        show('Создана копия: '+output)
        show('Загрузите её в HOI4 и сразу сохраните под другим именем на паузе. Затем подтвердите по новому сохранению. Загрузка движком пока не подтверждена.')
    def acknowledge_copy():
        path=state['path']; filename=filedialog.askopenfilename(title='Новое сохранение, сделанное HOI4 после загрузки подготовленной копии',filetypes=[('HOI4 save','*.hoi4')])
        if not filename: return
        b=read_json(path/'battle.json'); report=Ledger(path/'ledger.sqlite').acknowledge_save(b['id'],filename)
        write_json(path/'loaded_save_verification.json',report)
        show('Новое сохранение совпало с подготовленным результатом. Повторный перенос заблокирован.')
    for label,fn in [('Выбрать настоящее сражение из сохранения HOI4',export_saved),('Открыть описание боя JSON / тестовый пример',export),('Открыть сессию боя',session),
                     ('Прочитать результат Men of War',result),('Создать копию кампании с потерями и отступлением',prepare_copy),('Подтвердить копию по новому сохранению HOI4',acknowledge_copy),('Подготовить прежний вариант через консоль',stage),('Подтвердить команду по журналу HOI4',acknowledge)]:
        ttk.Button(frame,text=label,command=guarded(fn)).pack(fill='x',pady=3)
    show('Поддерживаются текстовые сохранения HOI4txt. Двоичные сохранения пока не читаются. Тестовый пример examples/battle.example.json содержит искусственные данные.')
    from .requests import RequestWatcher
    from .transition import AutomaticTransfer
    watcher=RequestWatcher(Path(config()['hoi4_user'])/'logs/game.log')
    automatic=AutomaticTransfer(config(),Path(__file__).resolve().parent.parent/'sessions/automatic')
    worker=ThreadPoolExecutor(max_workers=1);future=None
    def poll_requests():
        nonlocal future
        try:
            for line in watcher.poll():
                request=automatic.request(line)
                if request:
                    show('Запрос HOI4 получен. Ожидаю новое сохранение на паузе; файл и папка боя будут выбраны автоматически.')
            if future and future.done():
                try:
                    report=future.result();state['path']=Path(report['path'])
                    show('Миссия автоматически создана из настоящего боя: '+report['combat_id'])
                    show('Папка: '+report['mission']['path'])
                    show('Загрузка Men of War ещё не подтверждена. HOI4 оставьте на паузе.')
                except Exception as error: show('Автоматический перенос остановлен: '+str(error))
                future=None
            if future is None:
                snapshot=automatic.find_fresh_snapshot()
                if snapshot:
                    show('Свежая кампания найдена. Подбираю карту и создаю войска…')
                    future=worker.submit(automatic.prepare,snapshot,config().get('auto_install_mow',False))
        except (OSError,BridgeError) as error: show('Автоматический переход: '+str(error))
        app.after(1500,poll_requests)
    app.after(1500,poll_requests)
    app.mainloop()
