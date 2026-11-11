# jarvan-memory

**Claude Code için kalıcı ve disiplinli hafıza.** Her oturum sıfırdan başlar;
jarvan-memory, bir önceki oturumun öğrendiğini bir sonrakine düz Markdown
notlardan oluşan bir klasörle taşır. Notları tek bir komut (`mem`) yazar,
tarihleri hep o damgalar; birkaç kanca da doğru notu doğru anda önüne koyar.

- Yalnız Python standart kütüphanesi. pip yok, ağ servisi yok, API anahtarı yok.
- Windows, macOS ve Linux. Python 3.9+ ve git gerekir (git: depoyu klonlamak ve `backup` modülü için).
- Notlar sizindir: herhangi bir editörle ya da Obsidian'la açılan sıradan bir klasör.

## Kurulum

Claude Code'a şunu söylemeniz yeterli:

> github.com/BurakErdemci/jarvan-memory reposunu oku ve kur.

Ajan `INSTALL.md`'yi izler. Önce Python'u (3.9 veya üstü) denetler, yoksa
nasıl kurulacağını söyler. Sonra size birkaç kısa soru sorar: adınız, ne iş
yaptığınız, hafıza klasörünün nerede duracağı, notların dili ve hangi isteğe
bağlı modülleri istediğiniz. Kurulum, `mem doctor` her denetimi geçtiğinde
(`N/N checks passing`) tamamlanmış sayılır. Hafıza bir sonraki Claude Code
oturumunda çalışmaya başlar.

Elle kurmak isterseniz:

```sh
git clone https://github.com/BurakErdemci/jarvan-memory
cd jarvan-memory
python install.py --name "Adınız" --about "Ne iş yaptığınız" --language Turkish --modules none --stemmer tr
```

## Ne yapar

**Oturum başında** kısa bir blok gösterir: profiliniz, `READ FIRST` işaretli
notlar, bu projenin son iş günlüğü satırları, açık devir notları ve
doğrulanmamış çıkarımların sayısı. Blok bir *kayıttır*, talimat değil;
tarihine bakılarak kullanılır.

**Her isteminizde** istem bir notla güçlü biçimde eşleşirse o notun ilgili
satır aralığını önerir (en az üç anlamlı kelime eşleşmeli; notun INDEX tetik
satırındaki kelimeler de sayılır). Eşleşme zayıfsa hiçbir şey söylemez; böylece
büyük bir hafıza her istemde küçük bir hafıza kadar yer kaplar.

**Bir komut hata verdiğinde** aynı hata daha önce bir nota yazılmışsa en çok
iki notu hatırlatır.

**Uzun bir oturum hafızaya hiçbir şey yazmadan bitmek üzereyken** bir kez
sorar: devreden iş var mı, kalıcı bir karar ya da ölçüm çıktı mı? Yazacak bir
şey yoksa dürüst bir günlük satırı yeter; uydurma bir kayıt istemez. Uzun bir
çalışma daha geçerse yeniden sorar.

**İş günlüğüne elle saat yazılmasını engeller.** Modelin saati yoktur; elle
yazılan saat uydurmadır. Tarihleri hep `mem` damgalar. Kapsam: Write, Edit,
MultiEdit ve NotebookEdit ile iş günlüğü klasörüne yazmak reddedilir; kabukta
hedefi iş günlüğü klasörü olan, elle saat içeren `>`, `>>`, `tee`, `cp`, `mv`,
`sed -i` komutları da reddedilir. `python -c` gibi yorumlayıcı tek satırlıkları
denetlenmez.

## Hafıza klasörü

```
AGENT.md      ajanların uyduğu sözleşme
INDEX.md      her not için bir tetik satırı
profile.md    sizin hakkınızda kalıcı bilgiler
topics/       kalıcı bilgi: gerekçeli kararlar, ölçümler
projects/     proje başına not
worklog/      yalnız eklenen iş günlüğü (aylık dosyalar)
handoffs/     sonraki oturuma devreden iş (beş başlıklı not)
inferences/   karantina: gözlemler ve doğrulanmamış iddialar
daily/        (isteğe bağlı) otomatik oturum özetleri
archive/      kapanan iş; silinmez
```

Klasör, dosya ve komut adları her dilde İngilizce kalır; notların metni sizin
dilinizde yazılır.

## `mem` komutları

Aşağıdaki örneklerde `mem`, kurucunun `command:` satırında yazdığı tam yoldur
(`~/.claude/jarvan-memory/bin/mem`).

| Komut | Ne işe yarar |
|---|---|
| `mem search "<soru>"` | Not, satır aralığı ve eşleşen satırlar |
| `mem log "<ne oldu>" --done` | İş günlüğüne bir satır (devreden iş varsa `--handoff <ad>`) |
| `mem handoff open "<başlık>"` / `close` / `list` | Devir notları; açık liste her seferinde notların kendisinden çıkarılır |
| `mem note new topics <Ad> --trigger "<soru/kelimeler>"` | Yeni not, INDEX satırıyla birlikte; benzer adlı not varsa reddeder |
| `mem infer claim "<iddia>" --scope project` | Karantinaya iddia |
| `mem verify` / `promote` / `refute` | Taze kanıtla doğrula, kalıcı nota taşı, çürüt (çürütülen kayıt silinmez) |
| `mem status` | Kısa durum |
| `mem doctor` | Kurulumu uçtan uca denetler |
| `mem uninstall` | Kurulumun eklediği her şeyi kaldırır; hafıza klasörü kalır |

Tam yol `~/.claude/jarvan-memory/bin/mem` (cmd ve PowerShell için `mem.cmd`).
Kısa `mem` için bu klasörü PATH'e ekleyebilirsiniz.

## İsteğe bağlı modüller

| Modül | Ne yapar | Bedeli |
|---|---|---|
| `summary` | Yeterince uzun her oturumun sonunda `daily/` klasörüne kısa bir özet yazar | Oturum başına bir `claude -p` çağrısı, aboneliğinizden (varsayılan model `sonnet`) |
| `backup` | Hafıza klasörünü git deposu yapar, her oturum sonunda commit atar; yalnız siz uzak depo eklediyseniz push eder | git gerekir |
| `sweep` | Haftada bir, ucuz bir model (`haiku`) doğrulanmamış iddiaları son kayıtlarla karşılaştırır ve birebir alıntıyla desteklenen çürütme **önerir**; hiçbir kaydı değiştirmez | Haftada bir küçük çağrı |

Türkçe notlar için `--stemmer tr` arama eki: "notlarımızda" araması "not"
geçen notu bulur.

## Kaldırma

```sh
~/.claude/jarvan-memory/bin/mem uninstall                     # hafıza klasörü kalır
```

Kaldırma, `settings.json`'a eklenen kancaları, `CLAUDE.md`'deki işaretli bloğu,
ayar yedeklerini ve çalışma klasörünü siler. Kurulumdan sonra ayarlara başka
bir şey eklenmediyse `settings.json` ve `CLAUDE.md` bayt bayt eski hâline döner
(sembolik ya da sabit bağlantı olan dosyalar bağlantılı kalır).

Uninstall always keeps the vault, including older vaults inside the app folder.
The legacy `--purge-vault` option is refused without changing anything. Remove
an unwanted vault separately by hand.

## Belgeler

- [docs/how-it-works.md](docs/how-it-works.md): okuma ve yazma yolu, karantina, kapılar
- [docs/design-principles.md](docs/design-principles.md): tasarım ilkeleri ve gerekçeleri
- [docs/agent-error-patterns.md](docs/agent-error-patterns.md): yapay zekâ ajanlarının tipik hataları, genel dersler olarak
- [INSTALL.md](INSTALL.md): kurulumu yapan ajan için adım adım yönerge

## Testler

```sh
python -m unittest discover -s tests
```

Testler gerçek giriş noktalarını sürer: kurucu, `settings.json`'a kayıtlı
kanca komutu (bash ile) ve `mem`. Hepsi geçici bir HOME içinde çalışır; gerçek
`~/.claude` klasörüne dokunmaz.

## Lisans

MIT. Bkz. [LICENSE](LICENSE) ve [NOTICE](NOTICE).
