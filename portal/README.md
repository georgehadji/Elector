# Portal πελατών

Ιδιωτική πρόσβαση ανά πελάτη (κόμμα ή υποψήφιος) στις αναλύσεις που έχει αγοράσει. Μόνο stdlib. Ο δημόσιος ιστότοπος (`out/`, Vercel) δεν αλλάζει· το portal τρέχει χωριστά, όπου το φιλοξενήσεις.

## Μοντέλο

- **Πελάτης (tenant)** = φάκελος `analysis/clients/<slug>/` (τοπικός, gitignored· αλλαγή με `STAVROI_CLIENTS`).
- **`client.json`** στον φάκελο ορίζει τι βλέπει και τι τρέχει:

```json
{"name": "ΝΙΚΗ", "party": 131, "rival": 108, "pair": {"base": "2023/june", "target": "2024/euro"},
 "modules": ["base", "venues", "targets", "nikh_targets_map"],
 "publish": [{"title": "Αναφορά", "file": "report.pdf", "note": "Η αναφορά για το κόμμα"}]}
```

- `publish`: λίστα επιτρεπτών αρχείων. Μόνο ό,τι αναφέρεται εδώ μπορεί να ανοιχτεί, με το ακριβές όνομα· οι σημειώσεις και τα ενδιάμεσα αρχεία του φακέλου δεν φαίνονται ποτέ.
- `modules`: ποιες αναλύσεις τρέχει ο runner (`analysis/client_all.py`) για αυτόν τον πελάτη· χωρίς αυτό τρέχουν όλες. Νέα ανάλυση για πελάτη = μια λέξη στη λίστα.
- **Χρήστες** ανήκουν σε έναν πελάτη (`data/portal.sqlite`, gitignored). Σύνδεση με κωδικό ή με σύνδεσμο μιας χρήσης.

## Εντολές

```powershell
python -X utf8 -m portal tenant <slug> "<όνομα>"
python -X utf8 -m portal user <email> <slug>
python -X utf8 -m portal link <email> [ώρες]      # σύνδεσμος σύνδεσης (μίας χρήσης)
python -X utf8 -m portal password <email>
python -X utf8 -m portal disable|enable <email>   # ή: off|on <slug> για ολόκληρο πελάτη
python -X utf8 -m portal list
python -X utf8 -m portal serve [--port=8080] [--host=127.0.0.1] [--insecure]
```

Το `--insecure` είναι μόνο για `http://localhost`. Σε δημόσια φιλοξενία βάλε μπροστά proxy με TLS (τα cookies είναι `Secure`) και όρισε `PORTAL_URL` για τους συνδέσμους. Δεν στέλνεται email ακόμη: ο σύνδεσμος τυπώνεται και τον στέλνεις εσύ.

## Ασφάλεια (τι ελέγχεται από τα tests)

Κάθε σελίδα πελάτη θέλει session του ίδιου πελάτη, αλλιώς 404 (δεν φαίνεται αν υπάρχει άλλος)· allowlist αρχείων και έλεγχος διαδρομής· κωδικοί scrypt, tokens σε SHA-256· CSRF σε φόρμες· ο σύνδεσμος δαπανάται με POST (οι σαρωτές mail δεν τον καίνε)· κλείδωμα μετά από 5 αποτυχίες σε 15 λεπτά· ίδια απάντηση για λάθος κωδικό και άγνωστο email· απενεργοποίηση χρήστη ή πελάτη τερματίζει τα sessions· cookies HttpOnly, SameSite=Lax, Secure.

Ανοιχτά για αργότερα: αποστολή email, 2FA, ρόλοι (τώρα όλοι οι χρήστες ενός πελάτη βλέπουν τα ίδια), περιορισμός ρυθμού ανά IP, audit log.
