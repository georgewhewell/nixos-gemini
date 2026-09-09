# Preserve complete mixer records except the two read-only physical jack states.
# A missing, duplicate or writable jack control is a configuration error.
/^numid=/ {
    skip = ($0 ~ /^numid=[0-9]+,iface=CARD,name='Headphone Jack'$/ ||
            $0 ~ /^numid=[0-9]+,iface=CARD,name='Headset Mic Jack'$/)
    if (skip) {
        if ($0 ~ /name='Headphone Jack'$/) headphones++
        else microphones++
    }
}
skip && /; type=/ {
    if ($0 !~ /access=r[^,]*,values=1/ || $0 ~ /access=[^,]*w/) invalid = 1
    readonly++
}
!skip { print }
END {
    if (headphones != 1 || microphones != 1 || readonly != 2 || invalid) {
        print "invalid or missing read-only headset jack controls" > "/dev/stderr"
        exit 1
    }
}
