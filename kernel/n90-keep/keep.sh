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
	t=; read -r t 2>/dev/null < "/run/keep/hold-$1"
	case "$t" in ''|*[!0-9]*) return 1 ;; esac
	[ "$(date +%s)" -lt "$t" ]
}

# Liveness without pidof: pidof reads every /proc/PID/cmdline, which takes
# each process's mmap lock. A reader that CFS then leaves waiting behind a
# busy tailscaled blocked Soy's own memory operations for 50 ms at a time.
# /proc/PID/comm needs no mm lock, and the shell reads it without forking.
alive() {
	if [ "$1" = soy ]; then f=/run/soy/renderer.pid; else f=/run/keep/$1.pid; fi
	p=; read -r p 2>/dev/null < "$f"
	c=; [ -n "$p" ] && read -r c 2>/dev/null < "/proc/$p/comm"
	[ -n "$c" ] && [ "$c" = "$2" ] && return 0
	for d in /proc/[0-9]*; do
		c=; read -r c 2>/dev/null < "$d/comm"
		if [ "$c" = "$2" ]; then
			echo "${d#/proc/}" > "$f"
			return 0
		fi
	done
	return 1
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
		echo $! > /run/keep/touch.pid
		say "started touch" ;;
	battery)
		nohup /usr/sbin/n90-battery serve >/run/n90-battery.log 2>&1 </dev/null &
		echo $! > /run/keep/battery.pid
		say "started battery" ;;
	wdt)
		nohup /usr/sbin/n90-wdt 60 10 >/run/n90-wdt.log 2>&1 </dev/null &
		echo $! > /run/keep/wdt.pid
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

comm_soy=soy comm_touch=n90-touch comm_battery=n90-battery comm_wdt=n90-wdt

say "keep started"
missing_soy=0 missing_touch=0 missing_battery=0 missing_wdt=0
while :; do
	for s in wdt soy touch battery; do
		eval "m=\$missing_$s"
		eval "comm=\$comm_$s"
		if ! installed "$s" || held "$s" || alive "$s" "$comm"; then
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
