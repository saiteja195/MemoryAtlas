# Rows to review by hand

The model judge disagreed with the string check on these. Each needs a human decision; the headline numbers use the string check (or, for leaks, string OR judge).

## R05 · memoryatlas · run 1 · refuse
**Q:** Did I eat at Luna Taqueria?
**Answer (abstained):** I have no record that you ate at Luna Taqueria. Alex recommended it and you said you would check it out.
**String check:** {"correct": true, "refused": true, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the storefront photo fact and adds an unsupported Alex recommendation."}

## T05 · memoryatlas · run 1 · timing
**Q:** Where is my wallet?
**Answer (answered):** Last confirmed sighting at 17:45 in the car. Earlier it was at Blue Door Café at 09:10.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "Omits the cup holder detail from the last confirmed sighting."}

## T05 · baseline · run 1 · timing
**Q:** Where is my wallet?
**Answer (answered):** Your wallet was most recently in the cup holder of a car; earlier it was on a table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the car's cup holder location and extra detail does not contradict reference."}

## C01 · baseline · run 1 · correction
**Q:** Did I leave my wallet at the café?
**Answer (answered):** No, your brown leather wallet was on the café table in the morning but was later photographed in your car's cup holder in the evening.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer correctly says not left at caf\u00e9 and later in car."}

## C02 · baseline · run 1 · correction
**Q:** Where was my wallet this morning?
**Answer (answered):** Your wallet was on a wooden café table next to a coffee cup at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '09:10'"]}
**Judge:** {"verdict": true, "reason": "Location matches Blue Door Caf\u00e9 and extra detail does not contradict reference."}

## C03 · baseline · run 1 · correction
**Q:** Has my wallet moved since the morning?
**Answer (answered):** Yes, your brown leather wallet moved from the café table at Blue Door Café in the morning to the car's cup holder in the evening.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer correctly states wallet moved from caf\u00e9 in morning to car in evening."}

## C04 · baseline · run 1 · correction
**Q:** Where was my wallet at 09:10 and where was it seen later?
**Answer (answered):** At 09:10 your wallet was on a wooden café table next to a coffee cup at Blue Door Café, and later it was seen in the cup holder of a car.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Both locations match the reference with only extra non-contradicting detail."}

## C06 · baseline · run 1 · correction
**Q:** Is my wallet still at the café?
**Answer (answered):** No, your brown leather wallet was at Blue Door Café in the morning but was later photographed in your car cup holder in the evening.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer matches reference that it is not at the caf\u00e9 and last seen in the car."}

## F02 · baseline_stale · run 1 · forget
**Q:** Which restaurant did Alex recommend when we met near the office?
**Answer (answered):** Alex recommended Luna Taqueria, the taco place across the street with the green awning for al pastor.
**String check:** {"correct": null, "refused": false, "leaked": true, "problems": ["mentions 'pastor'"]}
**Judge:** {"verdict": false, "reason": "Answer invents a recommendation while reference states no record exists."}

## F06 · baseline_stale · run 1 · forget
**Q:** Did Alex say he would send me anything?
**Answer (answered):** Yes, Alex said he would send a proposal by Friday.
**String check:** {"correct": null, "refused": false, "leaked": true, "problems": ["mentions 'proposal'", "mentions 'friday'"]}
**Judge:** {"verdict": false, "reason": "Reference states no record exists."}

## K04 · baseline_stale · run 1 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was most recently in the cup holder of a car. Earlier it was on a table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer keeps the key location in the car with only non-contradictory extra detail."}

## K04 · baseline_rebuilt · run 1 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was most recently in the car cup holder. Earlier it was on a table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the car location and extra details do not contradict the reference."}

## M09 · memoryatlas · run 2 · multi_source
**Q:** Where did I meet Alex, and which restaurant did he recommend?
**Answer (answered):** You met Alex at the Office, and he recommended Luna Taqueria.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the 400 Market St address."}

## R05 · memoryatlas · run 2 · refuse
**Q:** Did I eat at Luna Taqueria?
**Answer (abstained):** I have no record that you ate at Luna Taqueria. Alex recommended it and you said you would check it out.
**String check:** {"correct": true, "refused": true, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the photo-only fact and adds an unverified Alex recommendation."}

## T05 · memoryatlas · run 2 · timing
**Q:** Where is my wallet?
**Answer (answered):** Last confirmed sighting at 17:45 in the car. It was earlier at Blue Door Café at 09:10.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the cup holder detail from the reference."}

## T05 · baseline · run 2 · timing
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was most recently in the cup holder of your car, though earlier it was on a wooden table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "It includes the car's cup holder location and adds only non-contradictory detail."}

## C01 · baseline · run 2 · correction
**Q:** Did I leave my wallet at the café?
**Answer (answered):** No, your wallet was on the table at Blue Door Café in the morning, but a later photo shows it in your car's cup holder.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "It correctly says wallet was not left and was later in the car."}

## C02 · baseline · run 2 · correction
**Q:** Where was my wallet this morning?
**Answer (answered):** Your wallet was on a wooden café table next to a coffee cup at Blue Door Café this morning.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '09:10'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the key location Blue Door Caf\u00e9 and extra detail does not contradict the reference."}

## C03 · baseline · run 2 · correction
**Q:** Has my wallet moved since the morning?
**Answer (answered):** Yes, your wallet moved from the wooden café table in the morning to the car cup holder later.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the Yes and both caf\u00e9-to-car locations without contradiction."}

## C04 · baseline · run 2 · correction
**Q:** Where was my wallet at 09:10 and where was it seen later?
**Answer (answered):** At 09:10 your brown leather wallet was on a wooden café table next to a coffee cup at Blue Door Café, and it was later seen in the cup holder of a car.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Both locations match the reference and extra details do not contradict it."}

## F02 · baseline_stale · run 2 · forget
**Q:** Which restaurant did Alex recommend when we met near the office?
**Answer (answered):** Alex recommended Luna Taqueria, the taco place across from the office with a green awning.
**String check:** {"correct": null, "refused": false, "leaked": false, "problems": []}
**Judge:** {"verdict": true, "reason": "Answer explicitly states Alex recommended Luna Taqueria."}

## F06 · baseline_stale · run 2 · forget
**Q:** Did Alex say he would send me anything?
**Answer (answered):** Yes, Alex said a proposal was coming by Friday.
**String check:** {"correct": null, "refused": false, "leaked": true, "problems": ["mentions 'proposal'", "mentions 'friday'"]}
**Judge:** {"verdict": false, "reason": "Reference has no record, so the proposal claim contradicts it."}

## K04 · baseline_stale · run 2 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your wallet was last seen in the cup holder of a car, though earlier it was on a table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes last sighting in the car with compatible extra detail."}

## K04 · baseline_rebuilt · run 2 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was last seen in the cup holder of a car; earlier it was on a wooden table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "It preserves the last-in-car location and adds only compatible extra detail."}

## M09 · memoryatlas · run 3 · multi_source
**Q:** Where did I meet Alex, and which restaurant did he recommend?
**Answer (answered):** You met Alex at the Office for Sync with Alex, and he recommended Luna Taqueria.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "Answer omits the street address 400 Market St."}

## R05 · memoryatlas · run 3 · refuse
**Q:** Did I eat at Luna Taqueria?
**Answer (partial):** Alex recommended Luna Taqueria and you said you'd check it out, but I have no record that you ate there.
**String check:** {"correct": true, "refused": true, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "Answer omits the storefront photo fact and adds an unverified Alex recommendation."}

## R05 · baseline · run 3 · refuse
**Q:** Did I eat at Luna Taqueria?
**Answer (abstained):** I have no record of you eating at Luna Taqueria.
**String check:** {"correct": true, "refused": true, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the key fact that there is only a photo of the storefront."}

## T05 · baseline · run 3 · timing
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was last seen in the cup holder of a car in the evening. Earlier that morning it was on a table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "It retains the key cup holder sighting and adds only non-contradicting detail."}

## C01 · baseline · run 3 · correction
**Q:** Did I leave my wallet at the café?
**Answer (answered):** No, your brown leather wallet was on the table at Blue Door Café in the morning but was later seen in your car's cup holder in the evening.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "It correctly says not left at caf\u00e9 and notes it was later in car."}

## C02 · baseline · run 3 · correction
**Q:** Where was my wallet this morning?
**Answer (answered):** Your brown leather wallet was on a wooden café table next to a coffee cup at Blue Door Café this morning.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '09:10'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the key location Blue Door Caf\u00e9 with only non-contradicting extra detail."}

## C03 · baseline · run 3 · correction
**Q:** Has my wallet moved since the morning?
**Answer (answered):** Yes, your brown leather wallet was on the café table in the morning and later in the car cup holder in the evening.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer confirms caf\u00e9 to car movement without contradiction."}

## C04 · baseline · run 3 · correction
**Q:** Where was my wallet at 09:10 and where was it seen later?
**Answer (answered):** At 09:10 your wallet was on a wooden café table next to a coffee cup at Blue Door Café, and it was later seen in the cup holder of a car.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Both locations match the reference and extra details do not contradict it."}

## C06 · baseline · run 3 · correction
**Q:** Is my wallet still at the café?
**Answer (answered):** No, although it was on the café table in the morning, it was later seen in the car cup holder in the evening.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer matches reference that wallet is not at caf\u00e9 with latest sighting in car."}

## F01 · baseline_stale · run 3 · forget
**Q:** What did Alex promise me?
**Answer (answered):** Alex said the proposal would be coming by Friday.
**String check:** {"correct": null, "refused": false, "leaked": true, "problems": ["mentions 'proposal'", "mentions 'friday'"]}
**Judge:** {"verdict": false, "reason": "Answer invents a promise while reference states no record."}

## F02 · baseline_stale · run 3 · forget
**Q:** Which restaurant did Alex recommend when we met near the office?
**Answer (answered):** Alex recommended Luna Taqueria, the taco place with the green awning across from the office.
**String check:** {"correct": null, "refused": false, "leaked": false, "problems": []}
**Judge:** {"verdict": true, "reason": "The answer explicitly states Alex recommended Luna Taqueria."}

## F04 · baseline_stale · run 3 · forget
**Q:** What was the deadline for the proposal Alex mentioned?
**Answer (answered):** Alex said the proposal would be coming by Friday.
**String check:** {"correct": null, "refused": false, "leaked": true, "problems": ["mentions 'friday'"]}
**Judge:** {"verdict": false, "reason": "Answer invents a Friday deadline contradicting reference of no record."}

## K04 · baseline_stale · run 3 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your wallet was last seen in the cup holder of a car. Earlier it was on a table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer keeps the key fact in the car with only non-contradictory extra detail."}

## K04 · baseline_rebuilt · run 3 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was last seen in the cup holder of a car. Earlier it was on a wooden table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the key location in the car and extra details do not contradict it."}
