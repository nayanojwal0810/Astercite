import os
import platform
import shutil
import sqlite3
import subprocess


def get_os() -> str:
    """Detect operating system name and version."""
    try:
        system = platform.system()
        release = platform.release()
        version = platform.version()
        if system:
            details = f"{system} {release}".strip()
            if version:
                details += f" ({version})"
            return details
        return platform.platform() or "Not available"
    except Exception:
        return "Not available"


def get_cpu_name() -> str:
    """Detect CPU model name across Windows, Linux, and macOS."""
    if platform.system() == "Windows":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            if name and name.strip():
                return name.strip()
        except Exception:
            pass

    if platform.system() == "Linux":
        try:
            if os.path.exists("/proc/cpuinfo"):
                with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("model name"):
                            parts = line.split(":", 1)
                            if len(parts) > 1 and parts[1].strip():
                                return parts[1].strip()
        except Exception:
            pass

    if platform.system() == "Darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=True,
            )
            if res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass

    try:
        proc = platform.processor()
        if proc and proc.strip():
            return proc.strip()
    except Exception:
        pass

    return "Not available"


def get_architecture() -> str:
    """Detect machine hardware architecture."""
    try:
        arch = platform.machine()
        return arch if arch else "Not available"
    except Exception:
        return "Not available"


def get_cpu_cores() -> str:
    """Detect logical CPU core count."""
    try:
        cores = os.cpu_count()
        return str(cores) if cores is not None else "Not available"
    except Exception:
        return "Not available"


def get_total_ram() -> str:
    """Detect total system RAM in gigabytes."""
    if platform.system() == "Windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return f"{stat.ullTotalPhys / (1024 ** 3):.2f} GB"
        except Exception:
            pass

    if platform.system() == "Linux":
        try:
            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                kb = int(parts[1])
                                return f"{kb / (1024 ** 2):.2f} GB"
        except Exception:
            pass
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if pages > 0 and page_size > 0:
                total_bytes = pages * page_size
                return f"{total_bytes / (1024 ** 3):.2f} GB"
        except Exception:
            pass

    if platform.system() == "Darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                check=True,
            )
            bytes_val = int(res.stdout.strip())
            return f"{bytes_val / (1024 ** 3):.2f} GB"
        except Exception:
            pass

    return "Not available"


def get_free_disk() -> str:
    """Detect available disk space in gigabytes."""
    try:
        usage = shutil.disk_usage(".")
        return f"{usage.free / (1024 ** 3):.2f} GB"
    except Exception:
        return "Not available"


def get_python_version() -> str:
    """Detect installed Python version."""
    try:
        return platform.python_version() or "Not available"
    except Exception:
        return "Not available"


def get_sqlite_version() -> str:
    """Detect SQLite library version."""
    try:
        return sqlite3.sqlite_version or "Not available"
    except Exception:
        return "Not available"


def check_sqlite_fts5() -> str:
    """Check whether SQLite FTS5 extension is functional."""
    try:
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("CREATE VIRTUAL TABLE _fts_check USING fts5(content);")
        cursor.execute("INSERT INTO _fts_check (content) VALUES ('fts5 verification test');")
        rows = cursor.execute(
            "SELECT content FROM _fts_check WHERE _fts_check MATCH 'verification';"
        ).fetchall()
        conn.close()
        if rows and len(rows) == 1:
            return "Available"
        return "Not available"
    except Exception:
        return "Not available"


def get_git_version() -> str:
    """Detect installed Git version."""
    try:
        if not shutil.which("git"):
            return "Not available"
        res = subprocess.run(["git", "--version"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
        return "Not available"
    except Exception:
        return "Not available"


def check_docker() -> str:
    """Check whether Docker is installed."""
    try:
        if not shutil.which("docker"):
            return "Not available"
        res = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return f"Installed ({res.stdout.strip()})"
        return "Installed"
    except Exception:
        return "Not available"


def check_nvidia_gpu() -> str:
    """Check whether NVIDIA GPU management tools are available."""
    try:
        if shutil.which("nvidia-smi"):
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                gpu_names = ", ".join(
                    line.strip() for line in res.stdout.strip().splitlines() if line.strip()
                )
                return f"Available ({gpu_names})" if gpu_names else "Available"
            return "Available"
        if shutil.which("nvcc"):
            return "Available (nvcc found)"
        return "Not available"
    except Exception:
        return "Not available"


def check_llama_cpp_server() -> str:
    """Check whether llama.cpp server binary is available."""
    try:
        candidates = ["llama-server", "llama-server.exe", "server", "server.exe"]
        for candidate in candidates:
            if shutil.which(candidate):
                if candidate.startswith("llama"):
                    return f"Available ({candidate})"
                try:
                    res = subprocess.run(
                        [candidate, "--help"],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    combined = (res.stdout + res.stderr).lower()
                    if "llama" in combined:
                        return f"Available ({candidate})"
                except Exception:
                    pass
        return "Not available"
    except Exception:
        return "Not available"


def main() -> None:
    checks = [
        ("OS", get_os()),
        ("CPU", get_cpu_name()),
        ("Architecture", get_architecture()),
        ("CPU cores", get_cpu_cores()),
        ("RAM", get_total_ram()),
        ("Free disk", get_free_disk()),
        ("Python", get_python_version()),
        ("SQLite", get_sqlite_version()),
        ("FTS5", check_sqlite_fts5()),
        ("Git", get_git_version()),
        ("Docker", check_docker()),
        ("NVIDIA GPU", check_nvidia_gpu()),
        ("llama.cpp server", check_llama_cpp_server()),
    ]

    for label, val in checks:
        print(f"{label}: {val}")


if __name__ == "__main__":
    main()
