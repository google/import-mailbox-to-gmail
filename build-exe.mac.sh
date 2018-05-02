#! /bin/bash
# vi: ts=4 sw=4 et syntax=sh :

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1


NAME='import-mailbox-to-gmail'
BUILD_DIR="./build"

_uname="$(uname)"
case "${_uname}" in
    [dD]arwin)
        ;;
    *)
        die "OS not supported: ${_uname}"
        ;;
esac

TOOL_pyinstaller="$(which pyinstaller 2>/dev/null)"
TOOL_pyi_makespec="$(which pyi-makespec 2>/dev/null)"

if [[ -z "${TOOL_pyinstaller}" || -z "${TOOL_pyi_makespec}" ]]; then
    echo "Missing required tool: pyinstaller" >&2
    exit 1
fi

python2 \
    "${TOOL_pyi_makespec}" \
    --name "${NAME}" \
    --specpath "${BUILD_DIR}" \
    --console \
    --osx-bundle-identifier "${NAME}" \
    --onefile \
    import-mailbox-to-gmail.py
_exit_code="$?"

if [[ "${_exit_code}" -ne 0 ]]; then
    echo "Spec file generation failed" >&2
    exit ${_exit_code}
fi
         
python2 \
    "${TOOL_pyinstaller}" \
    --noconfirm \
    --clean \
    --workpath "${BUILD_DIR}" \
    --distpath="${BUILD_DIR}/exe/macos" \
    "${BUILD_DIR}/${NAME}.spec"
_exit_code="$?"

if [[ "${_exit_code}" -ne 0 ]]; then
    echo "Pyinstaller invocation failed" >&2
    exit ${_exit_code}
fi

