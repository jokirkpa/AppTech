// Test the XML formatting logic
const xmlInput = `SUMMARY:audit_log_info
<?xml version="1.0" encoding="UTF-8"?>
<imdata totalCount="61445">
  <aaaModLR affected="uni/fabric/configexp-userconfigBkupforTechSupport" cause="transition" changeSet="" childAction="" clientTag="" code="E4216792" created="2026-01-30T10:03:50.124-05:00" descr="User triggered action on Configuration Export Policy From IP:127.0.0.1" dn="subj-[uni/fabric/configexp-userconfigBkupforTechSupport]/mod-8589996037" id="8589996037" ind="special" modTs="never" sessionId="7mL1HF64TPuzRYTvQfvaZA==" severity="info" status="" trig="config" txId="576460752392456165" user="admin"/>`;

function formatXmlExtraPretty(xmlInput) {
    // Split input into lines
    let lines = xmlInput.split('\n');
    let formatted = '';
    
    // Process each line
    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];
        
        // Skip empty lines
        if (line.trim() === '') {
            continue;
        }
        
        // Rule 1: Remove leading spaces
        line = line.trimStart();
        
        // Rule 2: If line ends with >, add newline after it
        if (line.endsWith('>')) {
            formatted += line + '\n';
            continue;
        }
        
        // Rule 3: If line contains " followed by space, split at each occurrence
        // This handles XML attributes on single lines
        if (line.includes('" ')) {
            // Split by '" ' and rejoin with '"\n'
            let parts = line.split('" ');
            for (let j = 0; j < parts.length; j++) {
                if (j < parts.length - 1) {
                    formatted += parts[j] + '"\n';
                } else {
                    // Last part - check if it ends with >
                    if (parts[j].endsWith('>') || parts[j].endsWith('/>')) {
                        formatted += parts[j] + '\n';
                    } else {
                        formatted += parts[j];
                    }
                }
            }
        } else {
            // No special processing needed
            formatted += line + '\n';
        }
    }
    
    // Clean up - remove trailing whitespace and ensure consistent line breaks
    formatted = formatted.trim();
    return formatted;
}

const result = formatXmlExtraPretty(xmlInput);
console.log("=== OUTPUT ===");
console.log(result);
console.log("\n=== STATS ===");
console.log("Lines:", result.split('\n').length);
console.log("Characters:", result.length);
