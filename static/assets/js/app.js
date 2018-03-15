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
    $.ajax({url: '/devices',
    dataType: 'json',
    success: function(data){
      console.log(data)
      app.devices = data
    }})
  }
});

