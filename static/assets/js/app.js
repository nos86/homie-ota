var app = new Vue({
  el: '#wrapper',
  delimiters: ['<<','>>'], 
  data: {
    devices:[],
    firmwares: []
  },
  components: {
    
  },
  mounted: function () {
    $.ajax('/devices',
          {success: function(data){
            this.devices = data
          }})
    this.firmwares=[
        {name:'Corridor', 
         online:true, 
         power:80,
         firmware: "firmware",
         fw_version: "0.2.1",
         ip: "192.168.31.21",
         uptime:"2d 5:10:20",
         device_name: "device",
         homie_ver: "2.0.0",
         implementation: "ESP8266",
         mac: "A0:20:A6:07:32:5C",
         wifi: "musux_iot",
         mqtt_address: "musux.cloud",
         mqtt_port: "1883",
         mqtt_auth: true,
         ota: false},
        {name:'Corridor2', 
         online:true, 
         power:20,
         firmware: "firmware",
         fw_version: "0.2.1",
         ip: "192.168.31.21",
         uptime:"2d 5:10:20",
         device_name: "device",
         homie_ver: "2.0.0",
         implementation: "ESP8266",
         mac: "A0:20:A6:07:32:5C",
         wifi: "musux_iot",
         mqtt_address: "musux.cloud",
         mqtt_port: "1883",
         mqtt_auth: true,
         ota: true}
        ]
  }
});

