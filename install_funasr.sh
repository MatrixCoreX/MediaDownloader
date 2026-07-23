#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_NAME="${0##*/}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

VENV_DIR="${SCRIPT_DIR}/.venv"
PYTHON_BIN="${PYTHON:-python3}"
MODE="auto"
PRELOAD_MODELS=0
DRY_RUN=0

usage() {
    cat <<EOF
Usage: ${SCRIPT_NAME} [options]

Install FunASR dependencies into a local virtual environment.

Options:
  --venv PATH          Virtualenv path. Default: .venv under this repo
  --python COMMAND     Python command used to create the venv. Default: python3
  --mode auto|cpu|cuda Installation mode. Default: auto
  --cpu                Force CPU-only PyTorch wheels
  --cuda               Force CUDA-capable PyTorch wheels
  --preload-models     Download/cache SenseVoiceSmall and FSMN VAD after install
  --dry-run            Print the detected plan without installing
  -h, --help           Show this help

Examples:
  bash ${SCRIPT_NAME}
  bash ${SCRIPT_NAME} --cpu
  bash ${SCRIPT_NAME} --cuda --preload-models
  bash ${SCRIPT_NAME} --dry-run
EOF
}

log() {
    printf '==> %s\n' "$*" >&2
}

warn() {
    printf 'warning: %s\n' "$*" >&2
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

shell_join() {
    local arg
    for arg in "$@"; do
        printf '%q ' "$arg"
    done
}

has_nvidia_gpu() {
    command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1
}

python_version() {
    "$PYTHON_BIN" - <<'PY'
import sys
print(".".join(map(str, sys.version_info[:3])))
PY
}

check_python() {
    "$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("Python 3.9 or newer is required")
PY
}

parse_args() {
    while (($#)); do
        case "$1" in
            --venv)
                (($# >= 2)) || die "--venv requires a path"
                VENV_DIR="$2"
                shift 2
                ;;
            --python)
                (($# >= 2)) || die "--python requires a command"
                PYTHON_BIN="$2"
                shift 2
                ;;
            --mode)
                (($# >= 2)) || die "--mode requires auto, cpu, or cuda"
                MODE="$2"
                shift 2
                ;;
            --cpu)
                MODE="cpu"
                shift
                ;;
            --cuda)
                MODE="cuda"
                shift
                ;;
            --preload-models)
                PRELOAD_MODELS=1
                shift
                ;;
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                die "unknown option: $1"
                ;;
        esac
    done
}

detect_mode() {
    case "$MODE" in
        auto)
            if has_nvidia_gpu; then
                printf 'cuda\n'
            else
                printf 'cpu\n'
            fi
            ;;
        cpu|cuda)
            printf '%s\n' "$MODE"
            ;;
        *)
            die "--mode must be auto, cpu, or cuda"
            ;;
    esac
}

create_venv() {
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        log "Reusing virtualenv: ${VENV_DIR}"
        return
    fi
    if [[ -e "$VENV_DIR" ]]; then
        die "venv path exists but ${VENV_DIR}/bin/python is not executable"
    fi
    log "Creating virtualenv: ${VENV_DIR}"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
}

install_packages() {
    local venv_python="$1"
    local install_mode="$2"
    local os_name
    os_name="$(uname -s 2>/dev/null || printf 'unknown')"

    log "Upgrading pip"
    "$venv_python" -m pip install -U pip

    if [[ "$install_mode" == "cpu" && "$os_name" == "Linux" ]]; then
        log "Installing CPU-only PyTorch/Torchaudio"
        "$venv_python" -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
    else
        if [[ "$install_mode" == "cuda" && ! has_nvidia_gpu ]]; then
            warn "CUDA mode was requested, but nvidia-smi did not report a GPU"
        fi
        log "Installing default PyTorch/Torchaudio wheels"
        "$venv_python" -m pip install torch torchaudio
    fi

    log "Installing FunASR, ModelScope, and OpenCC"
    "$venv_python" -m pip install funasr modelscope opencc-python-reimplemented
}

verify_install() {
    local venv_python="$1"
    local install_mode="$2"

    log "Verifying installed packages"
    "$venv_python" - <<'PY'
import funasr
import modelscope
import opencc
import torch
import torchaudio

print("python: ok")
print("torch:", torch.__version__, "cuda:", torch.cuda.is_available())
print("torchaudio:", torchaudio.__version__)
print("funasr:", getattr(funasr, "__version__", "installed"))
print("modelscope:", getattr(modelscope, "__version__", "installed"))
print("opencc:", getattr(opencc, "__version__", "installed"))
PY

    if [[ "$install_mode" == "cuda" ]]; then
        if ! "$venv_python" - <<'PY'
import sys
import torch
sys.exit(0 if torch.cuda.is_available() else 1)
PY
        then
            warn "CUDA mode installed, but torch.cuda.is_available() is false"
        fi
    fi
}

preload_models() {
    local venv_python="$1"
    local install_mode="$2"
    local device="cpu"

    if [[ "$install_mode" == "cuda" ]]; then
        device="cuda:0"
    fi

    log "Preloading FunASR models on device: ${device}"
    "$venv_python" - "$device" <<'PY'
import sys
from funasr import AutoModel

device = sys.argv[1]
AutoModel(model="iic/SenseVoiceSmall", device=device, vad_model="fsmn-vad")
print("models: iic/SenseVoiceSmall, fsmn-vad")
PY
}

print_plan() {
    local install_mode="$1"
    local os_name
    os_name="$(uname -s 2>/dev/null || printf 'unknown')"

    printf 'install_plan:\n'
    printf '  repo: %s\n' "$SCRIPT_DIR"
    printf '  venv: %s\n' "$VENV_DIR"
    printf '  python: %s (%s)\n' "$PYTHON_BIN" "$(python_version)"
    printf '  os: %s\n' "$os_name"
    printf '  detected_nvidia_gpu: %s\n' "$(has_nvidia_gpu && printf 'yes' || printf 'no')"
    printf '  mode: %s\n' "$install_mode"
    if [[ "$install_mode" == "cpu" && "$os_name" == "Linux" ]]; then
        printf '  torch_command: '
        shell_join "$VENV_DIR/bin/python" -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
        printf '\n'
    else
        printf '  torch_command: '
        shell_join "$VENV_DIR/bin/python" -m pip install torch torchaudio
        printf '\n'
    fi
    printf '  funasr_command: '
    shell_join "$VENV_DIR/bin/python" -m pip install funasr modelscope opencc-python-reimplemented
    printf '\n'
    printf '  preload_models: %s\n' "$([[ "$PRELOAD_MODELS" == 1 ]] && printf 'yes' || printf 'no')"
}

main() {
    parse_args "$@"

    command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "python command not found: ${PYTHON_BIN}"
    check_python || die "Python 3.9 or newer is required"

    local install_mode
    install_mode="$(detect_mode)"
    print_plan "$install_mode"

    if [[ "$DRY_RUN" == 1 ]]; then
        exit 0
    fi

    create_venv
    local venv_python="${VENV_DIR}/bin/python"
    install_packages "$venv_python" "$install_mode"
    verify_install "$venv_python" "$install_mode"
    if [[ "$PRELOAD_MODELS" == 1 ]]; then
        preload_models "$venv_python" "$install_mode"
    fi

    log "Done"
    printf '\nUse this Python for FunASR runs:\n  %s\n' "$venv_python"
    printf '\nExample:\n  %s media_downloader.py --transcribe --transcribe-engine funasr "https://v.douyin.com/xxxx/"\n' "$venv_python"
    if [[ "$install_mode" == "cuda" ]]; then
        printf '  %s media_downloader.py --transcribe --transcribe-engine funasr --funasr-device cuda:0 "https://v.douyin.com/xxxx/"\n' "$venv_python"
    fi
}

main "$@"
