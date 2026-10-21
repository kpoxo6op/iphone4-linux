#!/bin/sh
# keep: restart the phone's own services when one stops, without the laptop.
#
# Busybox init respawns this script (an inittab entry added at boot), so it
# survives too. Every 2 s it checks Soy, the touch driver, the battery
# reader and the watchdog kicker. One that has been gone for 6 s is started
# the same way the boot starts it. Deploy tools that stop a service on
# purpose write an expiry time (epoch seconds) to /run/keep/hold-NAME first.
# When Soy needs a third restart within two minutes, the release before the
# current one becomes current again.
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
LOG=/run/keep/keep.log
mkdir -p /run/keep

say() { echo "$(date '+%F %T') $*" >> "$LOG"; }

held() {
	[ -f "/run/keep/hold-$1" ] || return 1
	until=$(cat "/run/keep/hold-$1" 2>/dev/null)
	case "$until" in ''|*[!0-9]*) return 1 ;; esac
	[ "$(date +%s)" -lt "$until" ]
}

start_soy() {
	cd /opt/soy || return
	now=$(date +%s)
	recent=$(awk -v now="$now" '$1 > now - 120' /run/keep/soy-starts 2>/dev/null | wc -l)
	prev=$(readlink previous)
	if [ "$recent" -ge 2 ] && [ -n "$prev" ] && [ "$prev" != "$(readlink current)" ]; then
		rm -f current.keep
		ln -s "$prev" current.keep && mv -Tf current.keep current
		: > /run/keep/soy-starts
		say "soy keeps stopping; went back to $prev"
	fi
	echo "$now" >> /run/keep/soy-starts
	scene=$(sed -n 's/.*"scene":"\([A-Za-z0-9_-]*\)".*/\1/p' /run/soy/status.json 2>/dev/null)
	arg=
	if [ -n "$scene" ] && grep -qx "$scene" current/scenes/index; then
		arg="--scene $scene"
	fi
	rm -f /run/soy/status.json
	# $arg is a checked scene ID or empty.
	# shellcheck disable=SC2086
	nohup /opt/soy/current/soy --assets /opt/soy/current/assets \
		--scenes /opt/soy/current/scenes --run /run/soy $arg \
		>/var/log/soy.log 2>&1 </dev/null &
	echo $! > /run/soy/renderer.pid
	say "started soy ($(readlink current)${scene:+, $scene})"
}

start() {
	case "$1" in
	soy) start_soy ;;
	touch)
		cd /opt/n90-touch && nohup ./n90-touch serve n90-z2.bin \
			>/run/n90-touch.log 2>&1 </dev/null &
		say "started touch" ;;
	battery)
		nohup /usr/sbin/n90-battery serve >/run/n90-battery.log 2>&1 </dev/null &
		say "started battery" ;;
	wdt)
		nohup /usr/sbin/n90-wdt 60 10 >/run/n90-wdt.log 2>&1 </dev/null &
		say "started watchdog kicker" ;;
	esac
}

installed() {
	case "$1" in
	soy) [ -x /opt/soy/current/soy ] ;;
	touch) [ -x /opt/n90-touch/n90-touch ] ;;
	battery) [ -x /usr/sbin/n90-battery ] ;;
	wdt) [ -x /usr/sbin/n90-wdt ] ;;
	esac
}

process() {
	case "$1" in
	soy) echo soy ;;
	touch) echo n90-touch ;;
	battery) echo n90-battery ;;
	wdt) echo n90-wdt ;;
	esac
}

say "keep started"
missing_soy=0 missing_touch=0 missing_battery=0 missing_wdt=0
while :; do
	for s in wdt soy touch battery; do
		eval "m=\$missing_$s"
		if ! installed "$s" || held "$s" || pidof "$(process "$s")" >/dev/null; then
			m=0
		else
			m=$((m + 1))
			if [ "$m" -ge 3 ]; then
				start "$s"
				m=0
			fi
		fi
		eval "missing_$s=\$m"
	done
	sleep 2
done
