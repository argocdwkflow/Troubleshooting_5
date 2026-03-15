CUSTOM_PATH="/etc/vx/bin /opt/VRTS/bin /opt/VRTSvcs/bin /usr/lib/vxvm/bin"

for NEW_PATH in ${CUSTOM_PATH}; do
    if [ -d "${NEW_PATH}" ]; then
        if type pathmunge >/dev/null 2>&1; then
            pathmunge "${NEW_PATH}" after
        else
            case ":$PATH:" in
                *":${NEW_PATH}:"*) ;;
                *) PATH="${PATH}:${NEW_PATH}" ;;
            esac
        fi
    fi
done
export PATH

if ! echo "${MANPATH}" | /bin/grep -q /opt/VRTS/man/ ; then
    if [ -d /opt/VRTS/man ]; then
        MANPATH="${MANPATH}:/opt/VRTS/man/"
    fi
fi
export MANPATH