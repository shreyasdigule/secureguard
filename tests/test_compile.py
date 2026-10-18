# Test compilation of problematic section
code1 = (
    "class Test:\n"
    "    def method1(self):\n"
    "        pass\n"
    "\n"
    "    def method2(self, cmd: dict):\n"
    "        pass\n"
)

try:
    compile(code1, '<test>', 'exec')
    print('Test 1 OK')
except Exception as e:
    print('Test 1 failed:', e)

code2 = (
    "class Test:\n"
    "    def method1(self):\n"
    "        pass\n"
    "\n"
    "    def method2(self, cmd: dict):\n"
    '        """Docstring."""\n'
    "        pass\n"
)

try:
    compile(code2, '<test>', 'exec')
    print('Test 2 OK')
except Exception as e:
    print('Test 2 failed:', e)

code3 = (
    "class Test:\n"
    "    def method1(self):\n"
    "        pass\n"
    "\n"
    "    def _on_command_submitted(self, cmd: dict):\n"
    '        """Handle command submission from form."""\n'
    "        if not self._auth:\n"
    "            return\n"
    "        self.sync.execute_command()\n"
)

try:
    compile(code3, '<test>', 'exec')
    print('Test 3 OK')
except Exception as e:
    print('Test 3 failed:', e)