
I want to redesign the filtering logic:

1) Remove sequences with RepetitionTime and EchoTime values greater than 15. 
2) Remove according to scanning sequences 
    drop if contains "SE" and not GR (T2, TSE, FLAIR)
    drop if contains "EP" (diffusion)
3)  IMAGE_TYPE_EXCLUSIONS = ["DERIVED", "SECONDARY"]
4) finally check SeriesDescription. If it has "t2", "adc", "dwi", "sdyn", "loc", "sub", "survey", "rec", "sustraccion" - remove.


I want to group it by TR, TE but name it as group1, group2 etc.

Within a group, if the series description is not similar, which can be computed using this code:
```
import os
import json
from difflib import SequenceMatcher

def sequence_similarity(seq_names):
    if not seq_names:
        return 0.0
    # Compare all pairs, return average similarity
    n = len(seq_names)
    if n == 1:
        return 1.0
    total = 0
    count = 0
    for i in range(n):
        for j in range(i+1, n):
            sim = SequenceMatcher(None, seq_names[i], seq_names[j]).ratio()
            total += sim
            count += 1
    return total / count if count else 1.0

def auto_flag_patients(filtered_json_dir, flag_output_path, similarity_threshold=0.8):
    results = {}
    files = [f for f in os.listdir(filtered_json_dir) if f.endswith('_filtered.json')]
    for fname in sorted(files):
        fpath = os.path.join(filtered_json_dir, fname)
        with open(fpath, 'r') as f:
            data = json.load(f)
        patient_id = list(data.keys())[0]
        groups = data[patient_id]
        if not groups:
            results[patient_id] = 'flag: empty'
            continue
        if len(groups) == 1:
            group_entries = list(groups.values())[0]
            seq_names = [entry['sequence_folder'] for entry in group_entries]
            sim = sequence_similarity(seq_names)
            if sim >= similarity_threshold:
                results[patient_id] = 'ok'
            else:
                results[patient_id] = f'flag: low similarity ({sim:.2f})'
        else:
            results[patient_id] = f'flag: multiple groups ({len(groups)})'
    with open(flag_output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Flag results saved to {flag_output_path}")

```
further investigate this group. If the any of the following is true:
1) Series description has 'dyn' in it
2) ContrastBolusAgent, ContrastBolusStartTime, ContrastBolusVolume not none

then keep only that sequence. If none of them is true, then keep all but flag this group. 


Pro Tip: In some MRI datasets, look at the ContentTime or TriggerTime. If all images in a series have the exact same timestamp but different ImageType values like SUBTRACTION, you are looking at post-processed data, not the raw temporal phases.