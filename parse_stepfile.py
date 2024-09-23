import re

class PartialParse:
    def __init__(self):
        self.meta_data = None
        self.modes = None

class FullParse:
    def __init__(self):
        self.offset = None
        self.bpms = None
        self.stops = None
        self.tracks = None

# Step One Of Parsing #
def get_partial_parse(file_contents):
    partial_parse = PartialParse()
    
    # Match any metadata tag excluding the "NOTES" tag (case-insensitive)
    # Note: it will also match metadata tags that are blank, e.g. "#STOPS:;"
    pattern = r"#(?![nN][oO][tT][eE][sS])([^:]+):([^;]*);"
    matches = re.findall(pattern, file_contents)
    meta_data = {}
    for match in matches:
        tag_name = match[0].strip().replace("\n", "").upper()
        tag_data = match[1].strip().replace("\n", "")
        meta_data[tag_name] = tag_data
    partial_parse.meta_data = meta_data

    # Get "NOTES" sections (case-insensitive). The first five values are postfixed with a colon.
    # Note data comes last, postfixed by a semicolon.
    pattern = r"#[nN][oO][tT][eE][sS]:([^:]*):([^:]*):([^:]*):([^:]*):([^:]*):([^;]+;)"
    matches = re.findall(pattern, file_contents)
    modes = []
    field_names = ["type", "desc/author", "difficulty", "meter", "radar"]
    for match in matches:
        mode = {}
        for j in range(len(match) - 1):
            field_name = field_names[j]
            field_data = match[j].strip().replace("\n", "")
            mode[field_name] = field_data
        mode["NOTES"] = match[-1]
        modes.append(mode)
    partial_parse.modes = modes

    return partial_parse

# Step Two Of Parsing #
def get_full_parse(mode_index, partial_parse):
    full_parse = FullParse()

    unparsed_notes_string = partial_parse.modes[mode_index]["NOTES"]
    unparsed_array = unparsed_notes_string.split("\n")

    # Split the lines into measures
    measures = []
    state = 0
    i = 0
    current_measure = []
    while i < len(unparsed_array):
        current_line = unparsed_array[i]
        if state == 0:
            if "//" not in current_line and current_line.strip() != "":
                state = 1
            else:
                i += 1
        elif state == 1:
            if ("," not in current_line) and (";" not in current_line) and (current_line.strip() != ""):
                current_measure.append(current_line.strip())
                i += 1
            else:
                state = 2
        elif state == 2:
            measures.append(current_measure)
            current_measure = []
            i += 1
            state = 0

    # Split the measures into lines, and compute the beat position of each line
    line_infos = []
    current_beat = 0
    for measure in measures:
        for i, line in enumerate(measure):
            all_zeros = True
            for c in line:
                if c != "0":
                    all_zeros = False
                    break

            measure_divisions = len(measure)
            if not all_zeros: # don't write to the array if the line doesn't have any notes in it
                measure_position = i

                # compute the beat fraction, aka quantization, aka snap
                beat_fraction = measure_divisions
                for divisor in range(measure_divisions, 1, -1):
                    if measure_divisions % divisor == 0 and measure_position % divisor == 0:
                        beat_fraction = measure_divisions // divisor
                
                line_infos.append({
                    "end_beat": current_beat,
                    "line_string": line,
                    "measure": {
                        "divisions": measure_divisions,
                        "position": measure_position,
                        "fraction": beat_fraction
                    }
                })
            
            # assumes 4/4 time signature (4 beats per measure)
            current_beat += 4 / measure_divisions

    offset = float(partial_parse.meta_data["OFFSET"])

    bpms_string = partial_parse.meta_data["BPMS"]
    bpms_array = parse_float_equals_float_pattern(bpms_string)
    bpms = [{"beat": beat, "bpm": bpm} for beat, bpm in bpms_array]

    stops_string = partial_parse.meta_data["STOPS"]
    stops_array = parse_float_equals_float_pattern(stops_string)
    stops = [{"beat": beat, "duration": duration} for beat, duration in stops_array]

    # Compute the time position of each line
    # Note: start_beat and end_beat are the start and end beats of a line,
    # and then we need to handle stops and bpm changes that may occur within that range.
    current_time = -offset
    start_beat = 0
    for line_info in line_infos:
        end_beat = line_info["end_beat"]
        previous_beat = start_beat
        elapsed_time = 0

        # find the index of the current bpm
        current_bpm_index = 0
        for i in range(1, len(bpms)):
            if bpms[i]["beat"] < start_beat:
                current_bpm_index = i

        # start by adding the elapsed time due to stops (if any)
        for i in range(len(stops)):
            stop_beat = stops[i]["beat"]
            if start_beat <= stop_beat and stop_beat < end_beat:
                elapsed_time += stops[i]["duration"]

        while True:
            if current_bpm_index + 1 < len(bpms):
                next_bpm_change = bpms[current_bpm_index + 1]["beat"]
            else:
                next_bpm_change = float("inf")

            next_beat = min(end_beat, next_bpm_change)
            elapsed_time += (next_beat - previous_beat) / bpms[current_bpm_index]["bpm"] * 60
            previous_beat = next_beat
            current_bpm_index += 1

            if not previous_beat < end_beat:
                break
        
        current_time += elapsed_time

        line_info["time_in_seconds"] = current_time
        start_beat = end_beat

    num_tracks = len(line_infos[0]["line_string"])
    tracks = [[] for i in range(num_tracks)]
    for line in line_infos:
        for i, note_type in enumerate(line["line_string"]):
            if note_type != "0":
                note = {
                    "measure": line["measure"],
                    "time_in_seconds": line["time_in_seconds"],
                    "end_beat": line["end_beat"],
                    "type": note_type,
                    "track_number": i
                }
                tracks[i].append(note)
    full_parse.tracks = tracks

    return full_parse

def parse_float_equals_float_pattern(string):
    if "=" not in string: # handles the case of no stops
        return []
    return [
        [float(x), float(y)] for x, y in
        (s.strip().split("=") for s in string.split(","))
    ]
