#!/usr/bin/env python3
"""
Motorfest Settings Tweaker
==========================

Внешний редактор конфигов The Crew Motorfest (PC).

Инструмент НЕ трогает процесс игры, exe или память (в игре стоит BattlEye),
а правит только XML-файлы настроек в  Documents\\TheCrewMotorfest\\ .

Команды:
    scan              показать все найденные файлы и параметры
    apply PRESET...   применить пресет(ы) из папки presets (или путь к .json)
    set KEY=VALUE...  поменять отдельные параметры вручную
    restore           откатить последнюю резервную копию
    lock / unlock     сделать файлы настроек «только для чтения» (игра не перезапишет)

Общие опции:
    --dir PATH        явно указать папку с конфигами
    --dry-run         показать, что изменится, но не записывать
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

APP_DIR_NAME = "TheCrewMotorfest"
BACKUP_DIR_NAME = "_tweaker_backups"
HERE = Path(__file__).resolve().parent
PRESETS_DIR = HERE / "presets"

# Файлы, которые не трогаем при apply/set без явного --include-bindings.
BINDINGS_RE = re.compile(r"^bindings_", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Поиск папки с конфигами
# --------------------------------------------------------------------------- #
def _windows_documents_dir() -> Path | None:
    """Реальная папка «Документы» (учитывает перенос в OneDrive / на другой диск)."""
    try:
        import winreg  # type: ignore
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        value, _ = winreg.QueryValueEx(key, "Personal")
        winreg.CloseKey(key)
        return Path(os.path.expandvars(value))
    except OSError:
        return None


def candidate_dirs() -> list[Path]:
    out: list[Path] = []
    docs = _windows_documents_dir()
    if docs:
        out.append(docs / APP_DIR_NAME)
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    out.append(home / "Documents" / APP_DIR_NAME)
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(env):
            out.append(Path(os.environ[env]) / "Documents" / APP_DIR_NAME)
            out.append(Path(os.environ[env]) / "Документы" / APP_DIR_NAME)
    out.append(home / "Документы" / APP_DIR_NAME)
    # Linux / Steam Deck (Proton)
    for lib in (home / ".steam/steam", home / ".local/share/Steam"):
        out.append(
            lib / "steamapps/compatdata/2698940/pfx/drive_c/users/steamuser/Documents" / APP_DIR_NAME
        )
    seen, uniq = set(), []
    for p in out:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def find_config_dir(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_dir():
            die(f"Папка не найдена: {p}")
        return p
    for p in candidate_dirs():
        if p.is_dir() and any(p.glob("*.xml")):
            return p
    msg = ["Не нашёл папку с настройками The Crew Motorfest. Проверял:"]
    msg += [f"  - {p}" for p in candidate_dirs()]
    msg.append("Запустите игру хотя бы один раз или укажите папку: --dir \"D:\\...\\TheCrewMotorfest\"")
    die("\n".join(msg))
    raise SystemExit  # для type checker


# --------------------------------------------------------------------------- #
# Чтение / запись с сохранением кодировки
# --------------------------------------------------------------------------- #
@dataclass
class XmlFile:
    path: Path
    text: str
    encoding: str
    bom: bytes

    @classmethod
    def load(cls, path: Path) -> "XmlFile":
        raw = path.read_bytes()
        for bom, enc in (
            (b"\xef\xbb\xbf", "utf-8"),
            (b"\xff\xfe", "utf-16-le"),
            (b"\xfe\xff", "utf-16-be"),
        ):
            if raw.startswith(bom):
                return cls(path, raw[len(bom):].decode(enc), enc, bom)
        try:
            return cls(path, raw.decode("utf-8"), "utf-8", b"")
        except UnicodeDecodeError:
            return cls(path, raw.decode("cp1252"), "cp1252", b"")

    def save(self) -> None:
        was_ro = not self.path.stat().st_mode & stat.S_IWRITE
        make_writable(self.path)
        self.path.write_bytes(self.bom + self.text.encode(self.encoding))
        if was_ro:  # сохраняем «замок», если он стоял
            set_readonly([self.path], True)


def make_writable(p: Path) -> None:
    try:
        mode = p.stat().st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(p, mode | stat.S_IWRITE)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Поиск параметров в XML
# --------------------------------------------------------------------------- #
# Параметр в XML может выглядеть по-разному, поддерживаем три формы:
#   1) атрибут:            <Graphics MotionBlur="1" .../>
#   2) элемент с текстом:  <MotionBlur>1</MotionBlur>
#   3) пара name/value:    <Option Name="MotionBlur" Value="1"/>
ATTR_RE = re.compile(r'(?P<pre>\s)(?P<name>[A-Za-z_][\w.\-:]*)\s*=\s*(?P<q>["\'])(?P<val>[^"\']*)(?P=q)')
ELEM_RE = re.compile(r"<(?P<tag>[A-Za-z_][\w.\-:]*)(?P<attrs>\s[^<>]*?)?>(?P<val>[^<>]*)</(?P=tag)\s*>")
TAG_RE = re.compile(r"<(?P<tag>[A-Za-z_][\w.\-:]*)(?P<attrs>\s[^<>]*?)?(?P<close>/?)>")
NAME_KEYS = ("name", "id", "key", "option", "setting")
VALUE_KEYS = ("value", "val", "v", "current")


def norm(s: str) -> str:
    return re.sub(r"[\s_\-.:]", "", s).lower()


@dataclass
class Setting:
    file: Path
    key: str          # отображаемое имя параметра
    value: str
    span: tuple[int, int]  # позиция значения в тексте
    kind: str         # attr | elem | pair


def iter_settings(xf: XmlFile) -> list[Setting]:
    text = xf.text
    found: list[Setting] = []
    # Убираем комментарии и пролог из рассмотрения, сохранив позиции
    masked = re.sub(r"<!--.*?-->|<\?.*?\?>", lambda m: " " * len(m.group(0)), text, flags=re.S)

    for tm in TAG_RE.finditer(masked):
        attrs = tm.group("attrs") or ""
        base = tm.start("attrs") if tm.group("attrs") else tm.end()
        parsed = [(a.group("name"), a.group("val"), base + a.start("val"), base + a.end("val"))
                  for a in ATTR_RE.finditer(attrs)]
        low = {n.lower(): (n, v, s, e) for n, v, s, e in parsed}
        name_attr = next((low[k] for k in NAME_KEYS if k in low), None)
        value_attr = next((low[k] for k in VALUE_KEYS if k in low), None)
        if name_attr and value_attr:
            found.append(Setting(xf.path, name_attr[1], value_attr[1], (value_attr[2], value_attr[3]), "pair"))
            skip = {name_attr[0].lower(), value_attr[0].lower()}
        else:
            skip = set()
        tag = tm.group("tag")
        for n, v, s, e in parsed:
            if n.lower() in skip or n.lower().startswith("xmlns"):
                continue
            found.append(Setting(xf.path, f"{tag}.{n}", v, (s, e), "attr"))

    for em in ELEM_RE.finditer(masked):
        val = em.group("val")
        if val.strip() == "" or "\n" in val:
            continue
        attrs = em.group("attrs") or ""
        nm = re.search(r'\b(?:name|id|key)\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
        key = nm.group(1) if nm else em.group("tag")
        found.append(Setting(xf.path, key, val, (em.start("val"), em.end("val")), "elem"))

    found.sort(key=lambda s: s.span[0])
    return found


def matches(setting: Setting, patterns: list[str], exact: bool) -> bool:
    leaf = norm(setting.key.split(".")[-1])
    full = norm(setting.key)
    for p in patterns:
        np_ = norm(p)
        if exact:
            if leaf == np_ or full == np_:
                return True
        elif np_ in leaf:
            return True
    return False


# --------------------------------------------------------------------------- #
# Преобразование значений с сохранением формата
# --------------------------------------------------------------------------- #
BOOL_FORMS = [("true", "false"), ("True", "False"), ("TRUE", "FALSE"),
              ("1", "0"), ("on", "off"), ("On", "Off"), ("yes", "no")]


def convert_value(current: str, wanted) -> str | None:
    """Приводит желаемое значение к формату текущего. None — значение не подходит."""
    cur = current.strip()
    if isinstance(wanted, bool) or (isinstance(wanted, str) and wanted.lower() in ("on", "off", "true", "false")):
        flag = wanted if isinstance(wanted, bool) else wanted.lower() in ("on", "true")
        for t, f in BOOL_FORMS:
            if cur in (t, f):
                return t if flag else f
        # Числовой уровень (0=выкл, 1..N=вкл)? Выключение — 0, включение не трогаем.
        if re.fullmatch(r"-?\d+", cur):
            return "0" if not flag else None
        if re.fullmatch(r"-?\d+\.\d+", cur):
            return ("0." + "0" * len(cur.split(".")[1])) if not flag else None
        return None
    if isinstance(wanted, (int, float)):
        if re.fullmatch(r"-?\d+", cur) and float(wanted).is_integer():
            return str(int(wanted))
        if re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", cur):
            decimals = len(cur.split(".")[1]) if "." in cur and "e" not in cur.lower() else 6
            s = f"{float(wanted):.{decimals}f}"
            return s
        return None
    return str(wanted)


# --------------------------------------------------------------------------- #
# Резервные копии
# --------------------------------------------------------------------------- #
def backup(cfg: Path, files: list[Path]) -> Path:
    dest = cfg / BACKUP_DIR_NAME / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    return dest


def latest_backup(cfg: Path) -> Path | None:
    root = cfg / BACKUP_DIR_NAME
    if not root.is_dir():
        return None
    dirs = sorted([d for d in root.iterdir() if d.is_dir()])
    return dirs[-1] if dirs else None


# --------------------------------------------------------------------------- #
# Команды
# --------------------------------------------------------------------------- #
def xml_files(cfg: Path, include_bindings: bool) -> list[Path]:
    files = sorted(cfg.glob("*.xml"))
    if not include_bindings:
        files = [f for f in files if not BINDINGS_RE.match(f.name)]
    return files


def cmd_scan(cfg: Path, args) -> int:
    print(f"Папка настроек: {cfg}\n")
    flt = [norm(x) for x in (args.filter or [])]
    for f in sorted(cfg.glob("*.xml")):
        xf = XmlFile.load(f)
        items = iter_settings(xf)
        if flt:
            items = [s for s in items if any(p in norm(s.key) for p in flt)]
        ro = "" if f.stat().st_mode & stat.S_IWRITE else "  [только чтение]"
        print(f"== {f.name}  ({len(items)} парам.){ro}")
        for s in items:
            print(f"   {s.key:<55} = {s.value}")
        print()
    if args.out:
        lines = []
        for f in sorted(cfg.glob("*.xml")):
            for s in iter_settings(XmlFile.load(f)):
                lines.append(f"{f.name}\t{s.key}\t{s.value}")
        Path(args.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"Список сохранён в {args.out}")
    return 0


def load_preset(name: str) -> dict:
    p = Path(name)
    if not p.suffix:
        p = PRESETS_DIR / f"{name}.json"
    elif not p.exists():
        p = PRESETS_DIR / p.name
    if not p.exists():
        avail = ", ".join(sorted(x.stem for x in PRESETS_DIR.glob("*.json")))
        die(f"Пресет не найден: {name}\nДоступные: {avail}")
    with p.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("name", p.stem)
    return data


def apply_rules(cfg: Path, rules: list[dict], args, title: str) -> int:
    files = xml_files(cfg, args.include_bindings)
    if not files:
        die(f"В {cfg} нет XML-файлов настроек.")
    loaded = {f: XmlFile.load(f) for f in files}
    edits: dict[Path, list[tuple[Setting, str]]] = {}
    unmatched: list[str] = []

    for rule in rules:
        pats = rule["match"] if isinstance(rule["match"], list) else [rule["match"]]
        exact = rule.get("exact", False)
        exclude = [norm(x) for x in rule.get("exclude", [])]
        hit = False
        for f, xf in loaded.items():
            if rule.get("file") and not re.search(rule["file"], f.name, re.I):
                continue
            for s in iter_settings(xf):
                if not matches(s, pats, exact):
                    continue
                if any(e in norm(s.key) for e in exclude):
                    continue
                new = convert_value(s.value, rule["value"])
                if new is None:
                    print(f"  ! {f.name}: {s.key} = {s.value!r} — формат не подходит для {rule['value']!r}, пропуск")
                    continue
                hit = True
                if new != s.value:
                    edits.setdefault(f, []).append((s, new))
        if not hit:
            unmatched.append(rule.get("label") or "/".join(pats))

    print(f"[{title}]")
    total = sum(len(v) for v in edits.values())
    for f, lst in edits.items():
        print(f"  {f.name}:")
        for s, new in lst:
            print(f"    {s.key:<50} {s.value} -> {new}")
    if not total:
        print("  Изменений нет (всё уже выставлено или параметры не найдены).")
    if unmatched:
        print("  Не найдено в конфиге (возможно, другое имя — посмотрите `scan`):")
        for u in unmatched:
            print(f"    - {u}")

    if args.dry_run or not total:
        if args.dry_run and total:
            print("\n--dry-run: ничего не записано.")
        return 0

    bdir = backup(cfg, list(edits))
    for f, lst in edits.items():
        xf = loaded[f]
        text = xf.text
        # Заменяем с конца, чтобы позиции не сдвигались. Дубликаты по span убираем.
        uniq = {s.span: new for s, new in lst}
        for (a, b), new in sorted(uniq.items(), reverse=True):
            text = text[:a] + new + text[b:]
        xf.text = text
        xf.save()
    print(f"\nГотово: изменено {total} парам. Резервная копия: {bdir}")
    if args.lock:
        set_readonly(list(edits), True)
        print("Файлы помечены «только для чтения».")
    return 0


def cmd_apply(cfg: Path, args) -> int:
    rules: list[dict] = []
    titles = []
    for name in args.presets:
        pr = load_preset(name)
        titles.append(pr["name"])
        rules.extend(pr["rules"])
    return apply_rules(cfg, rules, args, " + ".join(titles))


def parse_value(raw: str):
    low = raw.lower()
    if low in ("on", "off", "true", "false"):
        return low
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def cmd_set(cfg: Path, args) -> int:
    rules = []
    for pair in args.pairs:
        if "=" not in pair:
            die(f"Ожидалось KEY=VALUE, получено: {pair}")
        k, v = pair.split("=", 1)
        rules.append({"match": [k.strip()], "value": parse_value(v.strip()), "exact": True})
    return apply_rules(cfg, rules, args, "ручная правка")


def cmd_restore(cfg: Path, args) -> int:
    b = Path(args.backup) if args.backup else latest_backup(cfg)
    if not b or not b.is_dir():
        die("Резервных копий нет.")
    for f in b.glob("*.xml"):
        target = cfg / f.name
        if target.exists():
            make_writable(target)
        shutil.copy2(f, target)
        print(f"  восстановлен {f.name}")
    print(f"Восстановлено из {b}")
    return 0


def set_readonly(files: list[Path], ro: bool) -> None:
    for f in files:
        mode = f.stat().st_mode
        os.chmod(f, (mode & ~stat.S_IWRITE & ~stat.S_IWGRP & ~stat.S_IWOTH) if ro else (mode | stat.S_IWRITE))


def cmd_lock(cfg: Path, args, ro: bool) -> int:
    files = xml_files(cfg, include_bindings=True)
    set_readonly(files, ro)
    state = "только для чтения" if ro else "доступны для записи"
    for f in files:
        print(f"  {f.name}: {state}")
    if ro:
        print("\nИгра больше не сможет сбросить эти файлы. Чтобы менять настройки в меню игры — выполните unlock.")
    return 0


# --------------------------------------------------------------------------- #
def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    ap = argparse.ArgumentParser(prog="motorfest_tweaker", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="папка с конфигами (по умолчанию ищется автоматически)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--dry-run", action="store_true", help="только показать изменения")
        p.add_argument("--lock", action="store_true", help="после записи сделать файлы только для чтения")
        p.add_argument("--include-bindings", action="store_true", help="разрешить правку Bindings_*.xml")

    p = sub.add_parser("scan", help="показать все параметры")
    p.add_argument("filter", nargs="*", help="показать только параметры, содержащие эти слова")
    p.add_argument("--out", help="сохранить список в файл")

    p = sub.add_parser("apply", help="применить пресет(ы)")
    p.add_argument("presets", nargs="+")
    common(p)

    p = sub.add_parser("set", help="задать параметры вручную: KEY=VALUE")
    p.add_argument("pairs", nargs="+")
    common(p)

    p = sub.add_parser("restore", help="откатить из резервной копии")
    p.add_argument("--backup", help="конкретная папка копии (по умолчанию последняя)")

    sub.add_parser("lock", help="запретить игре перезаписывать конфиги")
    sub.add_parser("unlock", help="снять запрет записи")
    sub.add_parser("presets", help="список пресетов")

    args = ap.parse_args(argv)

    if args.cmd == "presets":
        for f in sorted(PRESETS_DIR.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            print(f"  {f.stem:<18} {d.get('description', '')}")
        return 0

    cfg = find_config_dir(args.dir)
    if args.cmd == "scan":
        return cmd_scan(cfg, args)
    if args.cmd == "apply":
        return cmd_apply(cfg, args)
    if args.cmd == "set":
        return cmd_set(cfg, args)
    if args.cmd == "restore":
        return cmd_restore(cfg, args)
    if args.cmd == "lock":
        return cmd_lock(cfg, args, True)
    if args.cmd == "unlock":
        return cmd_lock(cfg, args, False)
    return 1


if __name__ == "__main__":
    sys.exit(main())
