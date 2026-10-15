# Phase 2 extraction & classification report

Heuristic, evidence-based classification. `*` after a page label = untitled continuation page.
No ground truth exists for these PDFs; entries marked REVIEW need a human look.

| file | pages | method | OCR conf | segments (label pages) | payables | review |
|---|---:|---|---:|---|---:|---|
| DU-02.pdf | 20 | ocr:20 | 77.0 | INVOICE p1-20 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: page counter restarted on pages [3, 4, 6, 7, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19] but the document number is unchanged: kept as ONE segment; verify whether these are separate payables; pages [5, 8, 20] attached as untitled continuation; customs invoice: confirm it is a payable; low OCR confidence on pages [5, 8, 20] |
| DU-03.pdf | 12 | ocr:12 | 81.0 | INVOICE p1-2 [high]<br>SUPPORTING/shipping_document p3-12 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: customs invoice: confirm it is a payable<br>seg2: pages [6, 8, 9, 10, 11, 12] attached as untitled continuation |
| DU-05.pdf | 1 | ocr:1 | 84.6 | INVOICE p1-1 [medium] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: customs invoice: confirm it is a payable |
| DU-05s.pdf | 15 | ocr:15 | 78.2 | SUPPORTING/delivery_note p1-15 [high] | 0 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>no payable candidate: all content would be declined<br>seg1: pages [13, 14] attached as untitled continuation; low OCR confidence on pages [13, 14] |
| DU-06.pdf | 2 | ocr:2 | 88.5 | INVOICE p1-2 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: pages [2] attached as untitled continuation |
| DU-08.pdf | 1 | ocr:1 | 87.6 | NON_PAYABLE/payment_reminder p1-1 [high] | 0 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>no payable candidate: all content would be declined |
| DU-09.pdf | 2 | ocr:2 | 82.3 | NON_PAYABLE/form p1-1 [medium]<br>NON_PAYABLE/email p2-2 [high] | 0 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>no payable candidate: all content would be declined |
| DU-10.pdf | 1 | ocr:1 | 86.0 | CREDIT_MEMO p1-1 [medium] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| DU-11.pdf | 1 | ocr:1 | 88.6 | CREDIT_MEMO p1-1 [medium] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: negative total printed: confirm invoice vs credit memo |
| HLD-01.pdf | 1 | ocr:1 | 59.4 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: low OCR confidence on pages [1] |
| HLD-03.pdf | 1 | ocr:1 | 65.1 | INVOICE p1-1 [medium] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| HLD-05.pdf | 2 | ocr:2 | 83.3 | INVOICE/untitled_invoice_like p1-2 [low] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: low classification confidence |
| HLD-08.pdf | 1 | ocr:1 | 84.7 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: page marked copy/duplicate but no earlier matching segment: kept as payable |
| HLD-10.pdf | 2 | ocr:2 | 79.5 | INVOICE p1-2 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-01.pdf | 1 | ocr:1 | 87.3 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-02.pdf | 2 | ocr:2 | 87.0 | INVOICE p1-2 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-03.pdf | 2 | ocr:2 | 89.4 | INVOICE p1-1 [high]<br>SUPPORTING/payment_advice p2-2 [medium] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-04.pdf | 1 | ocr:1 | 92.9 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-06.pdf | 2 | ocr:2 | 89.3 | INVOICE p1-2 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-07.pdf | 1 | ocr:1 | 92.9 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-09.pdf | 2 | ocr:2 | 72.4 | INVOICE p1-1 [high]<br>SUPPORTING/customs_document p2-2 [medium] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: customs invoice: confirm it is a payable |
| INV-10.pdf | 1 | ocr:1 | 81.3 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-11.pdf | 1 | ocr:1 | 72.8 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-13.pdf | 1 | ocr:1 | 88.4 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-14.pdf | 1 | ocr:1 | 91.4 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-15.pdf | 1 | ocr:1 | 90.6 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-16.pdf | 2 | ocr:2 | 85.8 | INVOICE p1-2 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-19.pdf | 2 | ocr:2 | 87.5 | INVOICE/untitled_invoice_like p1-2 [low] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: pages [2] attached as untitled continuation; low classification confidence |
| INV-20.pdf | 2 | ocr:2 | 77.5 | INVOICE p1-2 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-21.pdf | 1 | ocr:1 | 76.7 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-23.pdf | 6 | empty:2,ocr:4 | 60.5 | INVOICE/untitled_invoice_like p1-3 [low]<br>SUPPORTING/customs_document p4-6 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>pages with no extracted text: [2, 3]<br>seg1: pages [2, 3] attached as untitled continuation; low classification confidence; customs invoice: confirm it is a payable; low OCR confidence on pages [2, 3]<br>seg2: pages [6] attached as untitled continuation |
| INV-25.pdf | 2 | ocr:2 | 84.7 | INVOICE p1-1 [high]<br>SUPPORTING/duplicate_copy p2-2 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg2: marked copy/duplicate of segment 1 (numeric overlap >= 0.8) |
| INV-26.pdf | 2 | ocr:2 | 78.7 | INVOICE p1-2 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-27.pdf | 2 | ocr:2 | 92.9 | INVOICE/untitled_invoice_like p1-2 [low] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: pages [1] attached as untitled continuation; low classification confidence |
| INV-28.pdf | 3 | ocr:3 | 89.0 | INVOICE p1-3 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: pages [2, 3] attached as untitled continuation |
| INV-31.pdf | 3 | text-layer:3 | - | INVOICE p1-3 [high] | 1 | seg1: pages [2, 3] attached as untitled continuation |
| INV-32.pdf | 1 | text-layer:1 | - | INVOICE p1-1 [high] | 1 | ok |
| INV-33.pdf | 1 | ocr:1 | 74.6 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan |
| INV-34.pdf | 3 | text-layer:3 | - | INVOICE p1-3 [high] | 1 | seg1: pages [2, 3] attached as untitled continuation |
| INV-35.pdf | 1 | ocr:1 | 91.7 | INVOICE p1-1 [high] | 1 | OCR ran without language packs: deu,est,por,tur,msa,fra,spa,nld,dan<br>seg1: page marked copy/duplicate but no earlier matching segment: kept as payable |
| INV-36.pdf | 1 | text-layer:1 | - | INVOICE p1-1 [high] | 1 | ok |
| INV-37.pdf | 1 | text-layer:1 | - | INVOICE p1-1 [high] | 1 | ok |

Processed 42 PDFs; 42 produced text; 39 payable candidates in total.
