
import io
p = r'C:\Users\nickd\Downloads\Project_AI\opencode_provider_manager.py'
s = io.open(p, encoding='utf-8').read()
i = s.find("def _ca_bundles")
print(s[i:i+1600] if i > 0 else "NOT FOUND _ca_bundles")
