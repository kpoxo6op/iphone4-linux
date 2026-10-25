#!/bin/sh
# n90-story: the phone writes a short story by itself, with no connection.
#
#   n90-story [--show]
#
# A 15-million-parameter TinyStories model (Karpathy's tinyllamas, MIT)
# runs through n90-llm, llama2.c's int8 runner with this phone's patches
# (kernel/n90-offline), at nice 19 so Soy's frames come first. It writes
# about 250 tokens in under a minute. The result replaces the "story" scene
# through n90-scene. The Wi-Fi keeper runs this once whenever the phone has
# had no connection for ten minutes.
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
DIR=/opt/n90-offline
MODEL=stories15M-q80.bin

# A deliberately published offline trip pack owns the day's library and its
# battery reserve. Removing/undoing the pack restores background stories.
if grep -q '^source: offline trip pack$' /opt/soy/current/scenes/*.md 2>/dev/null; then
	echo 'n90-story: offline trip pack active; keeping the library and energy reserve' >&2
	exit 3
fi

# A hot phone sheds optional work (kernel/n90-battery, /run/thermal/hot).
[ -e /run/thermal/hot ] && { echo "n90-story: the phone is hot; not now" >&2; exit 3; }

case $(date +%H) in
0[5-9] | 1[01]) start="One morning" ;;
1[2-6]) start="One afternoon" ;;
1[7-9] | 20) start="One evening" ;;
*) start="One night" ;;
esac
began=$(date +%s)
nice -n 19 "$DIR/n90-llm" "$DIR/$MODEL" -z "$DIR/tokenizer.bin" -t 0.8 -p 0.9 \
	-n 256 -s "$began" -i "$start" > /run/n90-story.txt 2> /run/n90-story.err ||
	{ echo "n90-story: the model failed: $(tail -1 /run/n90-story.err)" >&2; exit 1; }
took=$(( $(date +%s) - began ))

scene=/run/n90-story.md
{
	printf '%s\n' --- 'id: story' 'label: Story' 'accent: cyan' \
		"source: phone, n90-story, $MODEL" ---
	# Whole sentences only, one paragraph a line, Soy's Markdown marks literal.
	tr -d '\r' < /run/n90-story.txt | awk '
		{ text = text $0 "\n" }
		END {
			n = 0
			for (i = 1; i <= length(text); i++)
				if (index(".!?\"", substr(text, i, 1))) n = i
			m = split(substr(text, 1, n), lines, "\n")
			for (i = 1; i <= m; i++) {
				line = lines[i]
				gsub(/[*[`_]/, "\\\\&", line)
				if (line ~ /^[#>-]/) line = "\\" line
				if (line !~ /^ *$/) printf "%s\n\n", line
			}
		}'
	printf '*Written on this phone by a small story model (15 million parameters) in %s s, %s.*\n' \
		"$took" "$(date '+%d %b %H:%M' | sed 's/^0//')"
} > "$scene"
n90-scene put "$scene" "$1"
