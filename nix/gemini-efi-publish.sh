#!/bin/sh
# Publish immutable boot files, optionally switching a hash-pinned old default.
set -eu
umask 077
mode=$1
root=$2
source=$3
manifest=$4
previous_sha=${5:-}
case "$mode" in verify|install|activate) ;; *) exit 2 ;; esac
if [ "$mode" = activate ]; then
    [ "${#previous_sha}" -eq 64 ] || exit 1
    case "$previous_sha" in *[!0-9a-f]*) exit 1 ;; esac
    backup=$root/loader/loader.conf.gemini-backup-$previous_sha
fi
[ -d "$root" ] && [ ! -L "$root" ] || exit 1
[ -f "$manifest" ] && [ ! -L "$manifest" ] || exit 1
if [ "$mode" != verify ]; then
    [ -d "$source" ] && [ ! -L "$source" ] || exit 1
fi

# No pathname component may redirect publication outside the chosen filesystem.
parents() {
    base=$1
    rest=$2
    create=$3
    while [ "${rest#*/}" != "$rest" ]; do
        component=${rest%%/*}
        rest=${rest#*/}
        base=$base/$component
        [ ! -L "$base" ] || return 1
        if [ -e "$base" ]; then
            [ -d "$base" ] || return 1
        elif [ "$create" = yes ]; then
            mkdir "$base" || return 1
            chmod 0755 "$base" || return 1
        fi
    done
}
valid_record() {
    [ "${#sha}" = 64 ] || return 1
    case "$sha" in *[!0-9a-f]*) return 1 ;; esac
    case "$bytes" in ''|*[!0-9]*) return 1 ;; esac
    [ "$bytes" -gt 0 ] || return 1
    case "$relative" in ''|/*|*//*|.|./*|*/./*|*/.|..|../*|*/../*|*/..|*[!A-Za-z0-9/._-]*) return 1 ;; esac
}
match_file() {
    file=$1
    [ -f "$file" ] && [ ! -L "$file" ] || return 1
    [ "$(stat -c %s "$file")" = "$bytes" ] || return 1
    [ "$(sha256sum "$file" | cut -d' ' -f1)" = "$sha" ]
}
match_previous() {
    [ -f "$1" ] && [ ! -L "$1" ] || return 1
    [ "$(sha256sum "$1" | cut -d' ' -f1)" = "$previous_sha" ]
}

records=0
seen=
config_seen=no
while read -r sha bytes relative; do
    valid_record || exit 1
    records=$((records + 1))
    case " $seen " in *" $relative "*) exit 1 ;; esac
    seen="$seen $relative"
    if [ "$mode" = activate ]; then
        [ "$config_seen" = no ] || exit 1
        [ "$relative" != loader/loader.conf ] || config_seen=yes
    fi
    parents "$root" "$relative" no || exit 1
    if [ "$mode" != verify ]; then
        parents "$source" "$relative" no || exit 1
        match_file "$source/$relative" || exit 1
    fi
    if [ "$mode" = verify ] || [ -e "$root/$relative" ] || [ -L "$root/$relative" ]; then
        if ! match_file "$root/$relative"; then
            [ "$mode" = activate ] && [ "$relative" = loader/loader.conf ] || exit 1
            match_previous "$root/$relative" || exit 1
        fi
    fi
done < "$manifest"
[ "$records" -eq 5 ] || exit 1
if [ "$mode" = activate ]; then
    [ "$config_seen" = yes ] || exit 1
    [ -f "$root/loader/loader.conf" ] && [ ! -L "$root/loader/loader.conf" ] || exit 1
    if [ -e "$backup" ] || [ -L "$backup" ]; then match_previous "$backup" || exit 1; fi
fi
[ "$mode" != verify ] || exit 0

# A failed copy can leave already published, verified files. Re-running checks
# those exact bytes and skips them; different existing content always fails.
temporary=
trap 'if [ -n "$temporary" ]; then rm -f -- "$temporary"; fi' EXIT
trap 'exit 1' HUP INT TERM
while read -r sha bytes relative; do
    if [ -e "$root/$relative" ]; then
        if match_file "$root/$relative"; then continue; fi
        [ "$mode" = activate ] && [ "$relative" = loader/loader.conf ] || exit 1
        match_previous "$root/$relative" || exit 1
    fi
    parents "$root" "$relative" yes || exit 1
    destination=$root/$relative
    pending=$destination.gemini-upload.tmp
    [ ! -e "$pending" ] && [ ! -L "$pending" ] || exit 1
    (set -C; : > "$pending") || exit 1
    temporary=$pending
    cat "$source/$relative" > "$temporary" || exit 1
    match_file "$temporary" || exit 1
    chmod 0644 "$temporary"
    if [ "$mode" = activate ] && [ "$relative" = loader/loader.conf ]; then
        # All payload and entry records precede this one. Keep the old default
        # inode and sync both generations before atomically selecting the new.
        match_previous "$destination" || exit 1
        if [ ! -e "$backup" ] && [ ! -L "$backup" ]; then
            ln "$destination" "$backup" || exit 1
        fi
        match_previous "$backup" || exit 1
        sync
        match_previous "$destination" || exit 1
        mv -fT "$temporary" "$destination" || exit 1
    else
        # Hard-link publication refuses any existing destination.
        ln "$temporary" "$destination" || exit 1
        rm -- "$temporary"
    fi
    temporary=
done < "$manifest"
sync
