// Validate the built workbooks and decks with Microsoft's OWN Open XML SDK.
//
// WHY THIS EXISTS
//   opc_validate.py and check_chart_quality.py are hand-written: they encode the faults
//   we have actually hit, and nothing else. Twice on 2026-07-31 a workbook passed every
//   check we had and still made Excel offer to Recover — once for a missing
//   [Content_Types] override, once for a strCache declaring points it did not hold.
//   Both are schema violations, and the SDK below is the same definition Excel uses to
//   decide. It knows the rules we have not been bitten by yet.
//
//   It runs on a windows-latest runner, which is free and unlimited on a public repo and
//   ships .NET, so this costs nothing and adds no local dependency.
//
// WHAT IT CANNOT DO
//   Render anything. Microsoft does not licence Excel on hosted runners, so "is the
//   package valid" is answerable here and "does the chart look right" is not.
//
// Usage:  dotnet script validate_ooxml.csx -- <file> [<file> ...]

#r "nuget: DocumentFormat.OpenXml, 3.1.0"

using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;

var files = Args.ToList();
if (files.Count == 0) {
    Console.WriteLine("usage: validate_ooxml.csx -- <file> [<file> ...]");
    return 2;
}

int totalErrors = 0;
// Validate against the Office 2007 schema: the oldest version the deliverables claim to
// support, so anything it rejects would break for the widest set of readers.
var validator = new OpenXmlValidator(DocumentFormat.OpenXml.FileFormatVersions.Office2007);

foreach (var path in files) {
    if (!File.Exists(path)) { Console.WriteLine($"  MISSING  {path}"); totalErrors++; continue; }
    var name = Path.GetFileName(path);
    IEnumerable<ValidationErrorInfo> errors;

    try {
        if (path.EndsWith(".xlsx", StringComparison.OrdinalIgnoreCase)) {
            using var doc = SpreadsheetDocument.Open(path, false);
            errors = validator.Validate(doc).ToList();
        } else if (path.EndsWith(".pptx", StringComparison.OrdinalIgnoreCase)) {
            using var doc = PresentationDocument.Open(path, false);
            errors = validator.Validate(doc).ToList();
        } else {
            Console.WriteLine($"  SKIP     {name} (not xlsx/pptx)");
            continue;
        }
    } catch (Exception ex) {
        // Failing to OPEN is itself the strongest possible signal: Excel would not
        // manage it either.
        Console.WriteLine($"  FAIL     {name} — could not open: {ex.Message}");
        totalErrors++;
        continue;
    }

    var list = errors.ToList();
    if (list.Count == 0) {
        Console.WriteLine($"  OK       {name}");
        continue;
    }

    totalErrors += list.Count;
    Console.WriteLine($"  INVALID  {name} — {list.Count} schema error(s)");
    // Group identical messages: one malformed pattern repeated across 19 charts is one
    // fault, not nineteen, and printing it once keeps the log readable.
    foreach (var g in list.GroupBy(e => e.Description).OrderByDescending(g => g.Count()).Take(12)) {
        Console.WriteLine($"      x{g.Count(),-4} {g.Key}");
        Console.WriteLine($"             e.g. {g.First().Path?.XPath}");
    }
}

Console.WriteLine(totalErrors == 0
    ? "OOXML VALIDATION: PASS (Microsoft Open XML SDK)"
    : $"OOXML VALIDATION: FAIL — {totalErrors} error(s)");
return totalErrors == 0 ? 0 : 1;
