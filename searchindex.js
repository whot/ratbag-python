Search.setIndex({docnames:["index","modules","ratbag","ratbag.drivers"],envversion:{"sphinx.domains.c":2,"sphinx.domains.changeset":1,"sphinx.domains.citation":1,"sphinx.domains.cpp":4,"sphinx.domains.index":1,"sphinx.domains.javascript":2,"sphinx.domains.math":2,"sphinx.domains.python":3,"sphinx.domains.rst":2,"sphinx.domains.std":2,"sphinx.ext.intersphinx":1,sphinx:56},filenames:["index.rst","modules.rst","ratbag.rst","ratbag.drivers.rst"],objects:{"":[[2,0,0,"-","ratbag"],[2,0,0,"-","util"]],"ratbag.Action":[[2,1,1,"","Type"],[2,3,1,"","as_dict"],[2,4,1,"","type"]],"ratbag.Action.Type":[[2,2,1,"","BUTTON"],[2,2,1,"","MACRO"],[2,2,1,"","NONE"],[2,2,1,"","SPECIAL"],[2,2,1,"","UNKNOWN"]],"ratbag.ActionButton":[[2,3,1,"","as_dict"],[2,4,1,"","button"]],"ratbag.ActionMacro":[[2,1,1,"","Event"],[2,3,1,"","as_dict"],[2,4,1,"","events"],[2,4,1,"","name"]],"ratbag.ActionMacro.Event":[[2,2,1,"","INVALID"],[2,2,1,"","KEY_PRESS"],[2,2,1,"","KEY_RELEASE"],[2,2,1,"","NONE"],[2,2,1,"","WAIT_MS"]],"ratbag.ActionSpecial":[[2,1,1,"","Special"],[2,3,1,"","as_dict"],[2,4,1,"","special"]],"ratbag.ActionSpecial.Special":[[2,2,1,"","BATTERY_LEVEL"],[2,2,1,"","DOUBLECLICK"],[2,2,1,"","PROFILE_CYCLE_DOWN"],[2,2,1,"","PROFILE_CYCLE_UP"],[2,2,1,"","PROFILE_DOWN"],[2,2,1,"","PROFILE_UP"],[2,2,1,"","RATCHET_MODE_SWITCH"],[2,2,1,"","RESOLUTION_ALTERNATE"],[2,2,1,"","RESOLUTION_CYCLE_DOWN"],[2,2,1,"","RESOLUTION_CYCLE_UP"],[2,2,1,"","RESOLUTION_DEFAULT"],[2,2,1,"","RESOLUTION_DOWN"],[2,2,1,"","RESOLUTION_UP"],[2,2,1,"","SECOND_MODE"],[2,2,1,"","UNKNOWN"],[2,2,1,"","WHEEL_DOWN"],[2,2,1,"","WHEEL_LEFT"],[2,2,1,"","WHEEL_RIGHT"],[2,2,1,"","WHEEL_UP"]],"ratbag.Blackbox":[[2,3,1,"","add_recorder"],[2,2,1,"","directory"],[2,3,1,"","make_path"]],"ratbag.Button":[[2,2,1,"","action"],[2,3,1,"","as_dict"],[2,3,1,"","do_get_property"],[2,3,1,"","do_set_property"],[2,2,1,"","profile"],[2,3,1,"","set_action"],[2,4,1,"","types"]],"ratbag.CommitTransaction":[[2,3,1,"","complete"],[2,4,1,"","device"],[2,3,1,"","do_finished"],[2,2,1,"","finished"],[2,4,1,"","is_finished"],[2,4,1,"","seqno"],[2,4,1,"","success"],[2,4,1,"","used"]],"ratbag.ConfigError":[[2,2,1,"","message"]],"ratbag.Device":[[2,3,1,"","as_dict"],[2,3,1,"","commit"],[2,2,1,"","dirty"],[2,2,1,"","disconnected"],[2,3,1,"","do_commit"],[2,3,1,"","do_disconnected"],[2,3,1,"","do_get_property"],[2,3,1,"","do_resync"],[2,3,1,"","do_set_property"],[2,2,1,"","name"],[2,2,1,"","path"],[2,4,1,"","profiles"],[2,2,1,"","resync"]],"ratbag.Feature":[[2,2,1,"","device"],[2,2,1,"","dirty"],[2,3,1,"","do_get_property"],[2,3,1,"","do_set_property"],[2,4,1,"","index"]],"ratbag.Led":[[2,1,1,"","Colordepth"],[2,1,1,"","Mode"],[2,3,1,"","as_dict"],[2,2,1,"","brightness"],[2,2,1,"","color"],[2,4,1,"","colordepth"],[2,3,1,"","do_get_property"],[2,3,1,"","do_set_property"],[2,2,1,"","effect_duration"],[2,2,1,"","mode"],[2,4,1,"","modes"],[2,3,1,"","set_brightness"],[2,3,1,"","set_color"],[2,3,1,"","set_effect_duration"],[2,3,1,"","set_mode"]],"ratbag.Led.Colordepth":[[2,2,1,"","MONOCHROME"],[2,2,1,"","RGB_111"],[2,2,1,"","RGB_888"]],"ratbag.Led.Mode":[[2,2,1,"","BREATHING"],[2,2,1,"","CYCLE"],[2,2,1,"","OFF"],[2,2,1,"","ON"]],"ratbag.Profile":[[2,1,1,"","Capability"],[2,2,1,"","active"],[2,3,1,"","as_dict"],[2,4,1,"","buttons"],[2,4,1,"","capabilities"],[2,2,1,"","default"],[2,3,1,"","do_get_property"],[2,3,1,"","do_set_property"],[2,2,1,"","enabled"],[2,4,1,"","leds"],[2,2,1,"","name"],[2,2,1,"","report_rate"],[2,4,1,"","report_rates"],[2,4,1,"","resolutions"],[2,3,1,"","set_active"],[2,3,1,"","set_default"],[2,3,1,"","set_enabled"],[2,3,1,"","set_report_rate"]],"ratbag.Profile.Capability":[[2,2,1,"","DISABLE"],[2,2,1,"","INDIVIDUAL_REPORT_RATE"],[2,2,1,"","SET_DEFAULT"],[2,2,1,"","WRITE_ONLY"]],"ratbag.Ratbag":[[2,3,1,"","add_driver"],[2,3,1,"","create"],[2,2,1,"","device_added"],[2,3,1,"","do_device_added"],[2,3,1,"","do_start"],[2,3,1,"","start"]],"ratbag.Recorder":[[2,3,1,"","log_rx"],[2,3,1,"","log_tx"]],"ratbag.Resolution":[[2,1,1,"","Capability"],[2,2,1,"","active"],[2,3,1,"","as_dict"],[2,4,1,"","capabilities"],[2,2,1,"","default"],[2,3,1,"","do_get_property"],[2,3,1,"","do_set_property"],[2,2,1,"","dpi"],[2,4,1,"","dpi_list"],[2,2,1,"","enabled"],[2,3,1,"","set_active"],[2,3,1,"","set_default"],[2,3,1,"","set_dpi"],[2,3,1,"","set_enabled"]],"ratbag.Resolution.Capability":[[2,2,1,"","SEPARATE_XY_RESOLUTION"]],"ratbag.parser":[[2,1,1,"","Parser"],[2,1,1,"","Result"],[2,1,1,"","Spec"]],"ratbag.parser.Parser":[[2,3,1,"","from_object"],[2,3,1,"","to_object"]],"ratbag.parser.Result":[[2,2,1,"","object"],[2,2,1,"","size"]],"ratbag.parser.Spec":[[2,1,1,"","ConverterArg"],[2,2,1,"","convert_from_data"],[2,2,1,"","convert_to_data"],[2,2,1,"","endian"],[2,2,1,"","format"],[2,2,1,"","greedy"],[2,2,1,"","name"],[2,2,1,"","repeat"]],"ratbag.parser.Spec.ConverterArg":[[2,2,1,"","bytes"],[2,2,1,"","index"],[2,2,1,"","value"]],"ratbag.recorder":[[2,1,1,"","YamlDeviceRecorder"]],"ratbag.recorder.YamlDeviceRecorder":[[2,3,1,"","create_in_blackbox"],[2,3,1,"","log_ioctl_rx"],[2,3,1,"","log_ioctl_tx"],[2,3,1,"","log_rx"],[2,3,1,"","log_tx"],[2,3,1,"","start"]],"ratbag.util":[[2,1,1,"","DataFile"],[2,6,1,"","add_to_sparse_tuple"],[2,6,1,"","as_hex"],[2,6,1,"","find_hidraw_devices"],[2,6,1,"","load_data_files"]],"ratbag.util.DataFile":[[2,2,1,"","driver"],[2,2,1,"","driver_options"],[2,3,1,"","from_config_parser"],[2,2,1,"","matches"],[2,2,1,"","name"]],ratbag:[[2,1,1,"","Action"],[2,1,1,"","ActionButton"],[2,1,1,"","ActionMacro"],[2,1,1,"","ActionNone"],[2,1,1,"","ActionSpecial"],[2,1,1,"","Blackbox"],[2,1,1,"","Button"],[2,1,1,"","CommitTransaction"],[2,5,1,"","ConfigError"],[2,1,1,"","Device"],[2,1,1,"","Feature"],[2,1,1,"","Led"],[2,1,1,"","Profile"],[2,1,1,"","Ratbag"],[2,1,1,"","Recorder"],[2,1,1,"","Resolution"],[3,0,0,"-","drivers"],[2,0,0,"-","parser"],[2,0,0,"-","recorder"],[2,0,0,"-","util"]]},objnames:{"0":["py","module","Python module"],"1":["py","class","Python class"],"2":["py","attribute","Python attribute"],"3":["py","method","Python method"],"4":["py","property","Python property"],"5":["py","exception","Python exception"],"6":["py","function","Python function"]},objtypes:{"0":"py:module","1":"py:class","2":"py:attribute","3":"py:method","4":"py:property","5":"py:exception","6":"py:function"},terms:{"0":2,"00":2,"01":2,"02":2,"03":2,"04":2,"0x0203":2,"0x0504":2,"0x1":2,"1":2,"10":2,"1000":2,"101":2,"102":2,"103":2,"104":2,"1073741824":2,"1073741825":2,"1073741826":2,"1073741827":2,"1073741828":2,"1073741829":2,"1073741830":2,"1073741831":2,"1073741832":2,"1073741833":2,"1073741834":2,"1073741835":2,"1073741836":2,"1073741837":2,"1073741838":2,"1073741839":2,"1073741840":2,"1073741841":2,"1073741842":2,"11":2,"12":2,"13":2,"14":2,"15":2,"16":2,"17":2,"18":2,"2":2,"20":2,"24":2,"255":2,"26":2,"3":2,"34":2,"3h":2,"3s":2,"4":2,"4s":2,"5":2,"500":2,"6":2,"7":2,"8":2,"9":2,"boolean":2,"byte":2,"case":2,"class":2,"default":2,"enum":2,"final":2,"function":2,"int":2,"new":2,"return":2,"true":2,"while":2,A:2,And:2,BE:2,For:2,If:2,In:2,It:2,Not:2,ON:2,On:2,One:2,Or:2,The:2,There:2,These:2,To:2,With:2,__init__:2,__name__:2,_countingattr:2,_default:2,_resultobject:2,ab:2,abl:2,about:2,access:2,accord:2,accordingli:2,account:2,action:2,actionbutton:2,actionmacro:2,actionnon:2,actionspeci:2,activ:2,ad:2,add:2,add_driv:2,add_record:2,add_to_sparse_tupl:2,adjust:2,after:2,all:2,allow:2,alreadi:2,also:2,altern:2,alwai:2,ambigu:2,an:2,ani:2,api:2,appli:2,applic:2,ar:2,arg:2,argument:2,around:2,arrai:2,as_dict:2,as_hex:2,assert:2,assertionerror:2,assign:2,associ:2,asynchron:2,attempt:2,attribut:2,automat:2,avail:2,avoid:2,b:2,bar:2,base:2,battery_level:2,bb:2,becaus:2,been:2,befor:2,being:2,belong:2,between:2,bit:2,blackbox:2,bool:2,breath:2,bright:2,bs:2,button:2,bytearrai:2,cach:2,call:2,callabl:2,callback:2,caller:2,can:2,cannot:2,capabl:2,carri:2,cd:2,chang:2,checksum:2,checksum_spec:2,clamp:2,clash:2,classmethod:2,click:2,client:2,color:2,colordepth:2,commit:2,committransact:2,common:2,compar:2,compat:2,complet:2,config:2,configerror:2,configpars:2,configur:2,connect:2,consist:2,constructor:2,consum:2,contain:2,content:1,context:2,conveni:2,convers:2,convert:2,convert_from_data:2,convert_to_data:2,converterarg:2,correspond:2,count:2,counter:2,creat:2,create_in_blackbox:2,current:2,cycl:2,d:2,data:2,datafil:2,decod:2,def:2,delet:2,depth:2,describ:2,desir:2,detail:2,dev:2,devic:2,device_ad:2,deviceconfig:2,dict:2,dictionari:2,differ:2,directli:2,directori:2,dirti:2,disabl:2,disconnect:2,disk:2,do_commit:2,do_device_ad:2,do_disconnect:2,do_finish:2,do_get_properti:2,do_resync:2,do_set_properti:2,do_start:2,document:2,doe:2,done:2,doubleclick:2,down:2,dpi:2,dpi_list:2,driver:1,driver_opt:2,drivernam:2,driverunavail:2,e:2,each:2,effect_dur:2,either:2,element:2,emit:2,empti:2,emul:1,enabl:2,encod:2,encount:2,encourag:2,endia:2,endian:2,ensur:2,entri:2,enumer:2,eq:2,error:2,even:2,event:2,exampl:2,example_driv:[1,2],except:2,exclud:2,exist:2,expand:2,expos:2,f:2,fail:2,fals:2,far:2,featur:2,ff:2,field:2,file:2,filenam:2,filter:2,find_hidraw_devic:2,finish:2,first:2,five:2,fix:2,foo:2,format:2,from:2,from_config_pars:2,from_object:2,full:2,fulli:2,furthermor:2,g:2,gener:2,get:2,gi:2,given:2,glib:2,gobject:2,greater:2,greedi:2,guarante:2,h:2,ha:2,handl:2,happen:2,hardwar:2,hash:2,have:2,hb:2,helper:2,hh:2,hid:1,hidpp10:[1,2],hidpp20:[1,2],hidraw0:2,hidraw1:2,hidraw:2,host:2,hz:2,i:2,ident:2,idx:2,ignor:2,immedi:2,implement:2,includ:2,independ:2,index:[0,2],indic:2,individual_report_r:2,info:2,inform:2,init:2,initi:2,input:2,instanc:2,instanti:2,instead:2,integ:2,intenum:2,interact:2,intern:2,invalid:2,invers:2,invok:2,ioctl_nam:2,iow:2,is_finish:2,isinst:2,its:2,json:2,keep:2,kei:2,key_press:2,key_releas:2,keyword:2,known:2,lambda:2,last:2,le:2,least:2,led:2,left:2,len:2,length:2,libratbag:2,likewis:2,limit:2,list:2,listen:2,littl:2,load:2,load_data_fil:2,local:2,log:2,log_ioctl_rx:2,log_ioctl_tx:2,log_rx:2,log_tx:2,logger:2,logic:2,macro:2,mai:2,mainloop:2,make_path:2,manag:2,map:2,match:2,mayb:2,mean:2,messag:2,metadata:2,miss:2,mode:2,model:2,modul:[0,1],monochrom:2,more:2,most:2,mous:2,multipl:2,must:2,myattr:2,myobj:2,name:2,need:2,new_act:2,new_data:2,new_dpi:2,new_valu:2,newli:2,next:2,nich:2,non:2,none:2,normal:2,note:2,noth:2,notif:2,notifi:2,number:2,obj:2,object:2,occur:2,off:2,on_finish:2,onc:2,one:2,onli:2,oper:2,option:2,order:2,other:2,otherwis:2,output:2,outsid:2,overrid:2,packag:[0,1],pad_to:2,page:0,paramet:2,parent:2,parser:1,pass:2,path:2,pathlib:2,per:2,permit:2,physic:2,pick:2,plug:2,point:2,posit:2,possibl:2,prefix:2,prese:2,present:2,press:2,previous:2,primarili:2,print:2,produc:2,profil:2,profile_cycle_down:2,profile_cycle_up:2,profile_down:2,profile_up:2,properti:2,provid:2,provil:2,pspec:2,python:2,queri:2,queryabl:2,r:2,rais:2,rang:2,rare:2,ratbag:0,ratbagd:2,ratchet_mode_switch:2,rate:2,re:2,read:2,readi:2,receiv:2,recent:2,record:1,recover:2,reflect:2,releas:2,reli:2,remain:2,remaind:2,rememb:2,remov:2,repeat:2,replac:2,report:2,report_descriptor:2,report_r:2,repr:2,repres:2,request:2,requir:2,reset:2,resolut:2,resolution_altern:2,resolution_cycle_down:2,resolution_cycle_up:2,resolution_default:2,resolution_down:2,resolution_up:2,respect:2,respons:2,result:2,result_class:2,resync:2,rgb:2,rgb_111:2,rgb_888:2,roccat:[1,2],run:2,rx:2,s:2,same:2,scale:2,search:0,second:2,second_mod:2,see:2,self:2,send:2,sent:2,separ:2,separate_xy_resolut:2,seqno:2,sequenc:2,seri:2,session:2,set:2,set_act:2,set_bright:2,set_color:2,set_default:2,set_dpi:2,set_effect_dur:2,set_en:2,set_mod:2,set_report_r:2,setup:2,should:2,signal:2,signal_numb:2,silent:2,similar:2,simpl:2,simplerecord:2,simplest:2,singl:2,size:2,skip:2,so:2,softwar:2,some_crc:2,sort:2,sourc:2,spec:2,special:2,specif:2,specifi:2,start:2,state:2,statu:2,still:2,store:2,str:2,stream:2,string:2,stroke:2,struct:2,structur:2,subclass:2,submodul:1,subpackag:1,success:2,suppli:2,support:2,supported_devic:2,sync:2,t:2,take:2,test:2,than:2,thi:2,third:2,thread:2,three:2,time:2,timeout:2,timestamp:2,to_object:2,tpl:2,traceback:2,track:2,transact:2,treat:2,tri:2,trigger:2,triplet:2,tupl:2,turn:2,two:2,tx:2,type:2,typic:2,uncommit:2,uniqu:2,unknown:2,unless:2,unnam:2,unspecifi:2,unsupport:2,until:2,up:2,updat:2,upload:2,us:2,usual:2,utf:2,util:1,v:2,valu:2,wa:2,wai:2,wait_m:2,what:2,wheel_down:2,wheel_left:2,wheel_right:2,wheel_up:2,when:2,where:2,within:2,without:2,word:2,write:2,write_onli:2,x:2,xdg_state_hom:2,y:2,yaml:2,yamldevic:2,yamldevicerecord:2,yet:2,zero:2},titles:["Welcome to libratbag\u2019s documentation!","ratbag","ratbag package","ratbag.drivers package"],titleterms:{content:[0,2,3],document:0,driver:[2,3],emul:2,example_driv:3,hid:2,hidpp10:3,hidpp20:3,indic:0,libratbag:0,modul:[2,3],packag:[2,3],parser:2,ratbag:[1,2,3],record:2,roccat:3,s:0,submodul:[2,3],subpackag:2,tabl:0,util:2,welcom:0}})