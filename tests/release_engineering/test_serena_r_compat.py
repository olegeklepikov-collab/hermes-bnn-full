import importlib.util,unittest
from pathlib import Path
p=Path(__file__).resolve().parents[2]/'packaging/serena_r_compat.py';s=importlib.util.spec_from_file_location('r_compat',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def symbol(name,start,end,kind=12,line=0):return {'name':name,'kind':kind,'range':{'start':{'line':line,'character':start},'end':{'line':line,'character':end}}}
class RCompatTests(unittest.TestCase):
    def test_exact_container_only(self):
        a=symbol('example',0,40)
        self.assertEqual(m.singleline_function([a],0,22)['name'],'example')
        self.assertIsNone(m.singleline_function([a],0,40));self.assertIsNone(m.singleline_function([a],1,22));self.assertIsNone(m.singleline_function([symbol('value',0,40,13)],0,22))
    def test_innermost_and_no_input_mutation(self):
        a,b=symbol('outer',0,60),symbol('inner',20,40)
        got=m.singleline_function([a,b],0,30);self.assertEqual(got['name'],'inner');got['name']='changed';self.assertEqual(b['name'],'inner')
