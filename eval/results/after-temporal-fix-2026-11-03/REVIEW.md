# Rows to review by hand

The model judge disagreed with the string check on these. Each needs a human decision; the headline numbers use the string check (or, for leaks, string OR judge).

## M09 · memoryatlas · run 1 · multi_source
**Q:** Where did I meet Alex, and which restaurant did he recommend?
**Answer (answered):** You met Alex at the Office, and he recommended Luna Taqueria.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the address 400 Market St."}

## R05 · memoryatlas · run 1 · refuse
**Q:** Did I eat at Luna Taqueria?
**Answer (abstained):** I have no record that you ate at Luna Taqueria.
**String check:** {"correct": true, "refused": true, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the key fact that only a storefront photo exists."}

## T05 · memoryatlas · run 1 · timing
**Q:** Where is my wallet?
**Answer (answered):** Last confirmed sighting at 17:45 in the car; it had earlier been seen at Blue Door Café at 09:10.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the cup holder detail from the reference."}

## T05 · baseline · run 1 · timing
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was last seen in the car's cup holder; it was earlier on a wooden table next to a coffee cup at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the key location in the car's cup holder without contradicting the reference."}

## C01 · baseline · run 1 · correction
**Q:** Did I leave my wallet at the café?
**Answer (answered):** No. It was seen at Blue Door Café in the morning but later seen in your car cup holder.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer correctly says it was not left at the caf\u00e9 and was later in the car."}

## C03 · baseline · run 1 · correction
**Q:** Has my wallet moved since the morning?
**Answer (answered):** Yes, your brown leather wallet was on a wooden café table in the morning and later was in the car's cup holder.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "It confirms the caf\u00e9-to-car move with only extra non-contradicting detail."}

## C04 · baseline · run 1 · correction
**Q:** Where was my wallet at 09:10 and where was it seen later?
**Answer (answered):** At 09:10 your wallet was on a wooden café table next to a coffee cup at Blue Door Café, and later it was seen in the cup holder of a car.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Both locations match the reference and extra details do not contradict it."}

## C06 · memoryatlas · run 1 · correction
**Q:** Is my wallet still at the café?
**Answer (answered):** No. Last confirmed sighting at 17:45 in the car, after an earlier sighting at 09:10 at Blue Door Café.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It states a definite No with confirmed sighting while reference says no confirmation."}

## C06 · baseline · run 1 · correction
**Q:** Is my wallet still at the café?
**Answer (answered):** No, your wallet was later seen in the car's cup holder, though it was earlier on the table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer gives No with later car sighting matching the reference."}

## F06 · baseline_stale · run 1 · forget
**Q:** Did Alex say he would send me anything?
**Answer (answered):** Yes, Alex said he will send a proposal by Friday.
**String check:** {"correct": null, "refused": false, "leaked": true, "problems": ["mentions 'proposal'", "mentions 'friday'"]}
**Judge:** {"verdict": false, "reason": "Answer hallucinates a proposal promise when reference states no record."}

## K04 · baseline_stale · run 1 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was most recently seen in the cup holder of a car; earlier it was on a wooden table next to a coffee cup at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the car as last sighting with only non-contradictory extra detail."}

## M09 · memoryatlas · run 2 · multi_source
**Q:** Where did I meet Alex, and which restaurant did he recommend?
**Answer (answered):** You met Alex at the Office for Sync with Alex, and he recommended Luna Taqueria.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the key address detail 400 Market St."}

## R05 · memoryatlas · run 2 · refuse
**Q:** Did I eat at Luna Taqueria?
**Answer (abstained):** I have no record of you eating at Luna Taqueria.
**String check:** {"correct": true, "refused": true, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the key fact that there is only a photo of its storefront."}

## T05 · memoryatlas · run 2 · timing
**Q:** Where is my wallet?
**Answer (answered):** Last confirmed sighting at 17:45 at the car. It was previously seen at Blue Door Café at 09:10.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It omits the cup holder detail from the last sighting."}

## T05 · baseline · run 2 · timing
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was most recently in the cup holder of your car; earlier it was on a wooden table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the key cup holder location and extra details do not contradict reference."}

## C01 · baseline · run 2 · correction
**Q:** Did I leave my wallet at the café?
**Answer (answered):** No — although you photographed the brown leather wallet at Blue Door Café in the morning, you later photographed it in your car's cup holder.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer correctly states it was not left at caf\u00e9 and was later in the car."}

## C02 · baseline · run 2 · correction
**Q:** Where was my wallet this morning?
**Answer (answered):** Your brown leather wallet was on a wooden café table next to a coffee cup at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '09:10'"]}
**Judge:** {"verdict": true, "reason": "Answer gives the correct location Blue Door Caf\u00e9 and extra details do not contradict it."}

## C03 · baseline · run 2 · correction
**Q:** Has my wallet moved since the morning?
**Answer (answered):** Yes, your brown leather wallet was on a wooden table at Blue Door Café in the morning and later in the cup holder of a car.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "It reports movement from caf\u00e9 in morning to car later, matching reference."}

## C04 · baseline · run 2 · correction
**Q:** Where was my wallet at 09:10 and where was it seen later?
**Answer (answered):** At 09:10 your brown leather wallet was on a wooden café table next to a coffee cup at Blue Door Café, and later it was seen in the cup holder of a car.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Both locations match the reference and extra details do not contradict it."}

## F03 · baseline_stale · run 2 · forget
**Q:** What did Alex say about food?
**Answer (answered):** Alex recommended the taco place across from the office with the green awning for al pastor.
**String check:** {"correct": null, "refused": false, "leaked": true, "problems": ["mentions 'pastor'", "mentions 'taco place'"]}
**Judge:** {"verdict": false, "reason": "Answer invents taco details while reference states no record."}

## F04 · baseline_stale · run 2 · forget
**Q:** What was the deadline for the proposal Alex mentioned?
**Answer (answered):** Alex said he will send the proposal by Friday.
**String check:** {"correct": null, "refused": false, "leaked": true, "problems": ["mentions 'friday'"]}
**Judge:** {"verdict": false, "reason": "Reference has no record of a proposal so the Friday claim is unsupported."}

## K04 · baseline_stale · run 2 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your wallet was most recently in the cup holder of a car; earlier it was on a wooden table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the last location in the car with only compatible extra detail."}

## M09 · memoryatlas · run 3 · multi_source
**Q:** Where did I meet Alex, and which restaurant did he recommend?
**Answer (answered):** You met Alex at the Office for Sync with Alex, and he recommended Luna Taqueria.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "Answer omits the 400 Market St address from the reference."}

## R05 · baseline · run 3 · refuse
**Q:** Did I eat at Luna Taqueria?
**Answer (abstained):** I have no record of you eating at Luna Taqueria.
**String check:** {"correct": true, "refused": true, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "Omits the key fact that only a storefront photo exists."}

## T05 · baseline · run 3 · timing
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was last seen in the cup holder of a car; earlier it was on a wooden table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "It retains the cup holder location and adds no contradictory information."}

## C01 · baseline · run 3 · correction
**Q:** Did I leave my wallet at the café?
**Answer (answered):** No — although your wallet was photographed at Blue Door Café in the morning, it was later photographed in your car's cup holder in the evening.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer correctly denies wallet left at caf\u00e9 and notes later car photo."}

## C02 · baseline · run 3 · correction
**Q:** Where was my wallet this morning?
**Answer (answered):** Your brown leather wallet was on a wooden café table next to a coffee cup at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '09:10'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the key location Blue Door Caf\u00e9 and extra details do not contradict the reference."}

## C03 · baseline · run 3 · correction
**Q:** Has my wallet moved since the morning?
**Answer (answered):** Yes, your wallet was on a wooden café table in the morning and later in the cup holder of a car.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer states the caf\u00e9-to-car move without contradicting the reference times."}

## C04 · baseline · run 3 · correction
**Q:** Where was my wallet at 09:10 and where was it seen later?
**Answer (answered):** At 09:10 your brown leather wallet was on a wooden café table next to a coffee cup at Blue Door Café, and it was later seen in the cup holder of a car.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Both locations match the reference with only extra non-contradicting detail."}

## C06 · baseline · run 3 · correction
**Q:** Is my wallet still at the café?
**Answer (answered):** No. Your wallet was at Blue Door Café in the morning, but by 17:45 it was photographed in your car cup holder.
**String check:** {"correct": true, "refused": false, "leaked": null, "problems": []}
**Judge:** {"verdict": false, "reason": "It asserts definitively the wallet is not at the caf\u00e9 while the reference says no confirmation beyond the car sighting."}

## F01 · memoryatlas · run 3 · forget
**Q:** What did Alex promise me?
**Answer (abstained):** I have no record of what Alex promised.
**String check:** {"correct": null, "refused": true, "leaked": false, "problems": []}
**Judge:** {"verdict": true, "reason": "Answer matches reference by stating no record."}

## F01 · baseline_stale · run 3 · forget
**Q:** What did Alex promise me?
**Answer (answered):** Alex said a proposal would be coming by Friday.
**String check:** {"correct": null, "refused": false, "leaked": true, "problems": ["mentions 'proposal'", "mentions 'friday'"]}
**Judge:** {"verdict": false, "reason": "Answer invents a promise when reference says no record."}

## K04 · baseline_stale · run 3 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was last seen in the cup holder of a car; earlier it was on a wooden café table at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer preserves last sighting in the car and added details do not contradict reference."}

## K04 · baseline_rebuilt · run 3 · keep
**Q:** Where is my wallet?
**Answer (answered):** Your brown leather wallet was most recently in the cup holder of a car; earlier it was on a wooden table next to a coffee cup at Blue Door Café.
**String check:** {"correct": false, "refused": false, "leaked": null, "problems": ["missing '17:45'"]}
**Judge:** {"verdict": true, "reason": "Answer includes the key location in the car with only non-contradicting extra detail."}
